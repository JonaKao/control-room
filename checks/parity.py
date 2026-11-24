"""Same answers as before: the Rust core (`control-room serve`) answers every GET exactly as server.py.

For fixtures/workspace, fixtures/first-run and a temporary Git workspace (checks/git_workspace.py,
with the scheduler made a code repository for the change map), both servers serve the same folder
with the clock pinned, and for every project these must be equal: status code, content type and
JSON of /api/projects, /api/record, /api/project, /api/git, /api/files; the page itself; every plot
(bytes and type); and the refusals (unknown projects, path traversal, unknown paths).

Then Push and Pull through `serve` must give what tests/test_git.py expects of server.py: 403 without
the page's header or from a foreign Origin or Host, 404 for unknown actions and projects, a 4xx for a
bad Content-Length, 409 for Pull while the agent works, and a working Push and Pull otherwise (the
same codes and messages as server.py on a twin workspace).

Finally, the core must never run git itself: no `Command::new("git")` in app/src.

Allowed differences: none (ALLOWED below lists any, each recorded as a decision).
Only until feature 10 (the browser version retired): it needs server.py.
"""
import http.client
import json
import os
import re
import socket
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)
sys.path.insert(0, HERE)
import server  # noqa: E402
import app_server  # noqa: E402
import git_workspace as gw  # noqa: E402

NOW = "2026-10-14T14:50:00+02:00"
ALLOWED = {}  # (endpoint, json path) -> decision title; empty: no difference is allowed
HEADER = {"X-AAF-Request": "control-room", "Content-Type": "application/json"}
problems = []


def fetch(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=90) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def diff(a, b, where=""):
    """The first places where two JSON values differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append("%s/%s: %s" % (where, k, "only in server.py" if k in a else "only in the Rust core"))
            else:
                out += diff(a[k], b[k], "%s/%s" % (where, k))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return ["%s: %d items in server.py, %d in the Rust core" % (where, len(a), len(b))]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, "%s[%d]" % (where, i))
        return out
    numbers = isinstance(a, (int, float)) and isinstance(b, (int, float)) and isinstance(a, bool) == isinstance(b, bool)
    if a != b or (type(a) is not type(b) and not numbers):
        return ["%s: server.py %r, Rust core %r" % (where, a, b)]
    return []


def compare(label, py_base, rs_base, path):
    p, r = fetch(py_base, path), fetch(rs_base, path)
    if p[0] != r[0]:
        problems.append("%s %s: status %s (server.py) vs %s (Rust core)" % (label, path, p[0], r[0]))
        return
    if p[1] != r[1]:
        problems.append("%s %s: content type %r vs %r" % (label, path, p[1], r[1]))
    if "json" in p[1]:
        found = [d for d in diff(json.loads(p[2]), json.loads(r[2]))
                 if not any(re.match(re.escape(k) + r"\b", path + " " + d.split(":")[0]) for k in ALLOWED)]
        for d in found[:8]:
            problems.append("%s %s %s" % (label, path, d))
    elif p[2] != r[2]:
        problems.append("%s %s: %d bytes from server.py, %d from the Rust core, not the same" % (label, path, len(p[2]), len(r[2])))
    return p


def python_server(root):
    server.set_root(root)
    server.CLOCK = NOW
    for c in (server._git_cache, server._files_cache, server._stats_cache, server._estimate_cache):
        c.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.handle_error = lambda request, address: None  # a client closing early (bad length test) is expected
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def compare_workspace(label, root):
    httpd, py_base = python_server(root)
    try:
        with app_server.serve(root, clock=NOW) as rs_base:
            names = [p["name"] for p in json.loads(fetch(py_base, "/api/projects")[2])]
            paths = ["/", "/index.html", "/api/projects", "/api/record", "/nothing", "/api/project",
                     "/api/project?name=nope", "/api/project?name=..", "/api/git?name=../..",
                     "/api/files?name=..%2Fscheduler", "/plot?project=../..&file=loss.svg"]
            for name in names:
                paths += ["/api/project?name=" + name, "/api/project?project=" + name,
                          "/api/git?name=" + name, "/api/files?name=" + name,
                          "/plot?project=%s&file=../project.json" % name,
                          "/plot?project=%s&file=missing.png" % name]
            for path in paths:
                compare(label, py_base, rs_base, path)
            for name in names:
                detail = json.loads(fetch(py_base, "/api/project?name=" + name)[2])
                for plot in detail["plots"]:
                    compare(label, py_base, rs_base, "/plot?project=%s&file=%s" % (name, plot["file"]))
            return len(paths)
    finally:
        httpd.shutdown()
        httpd.server_close()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
    r = conn.getresponse()
    data = r.read()
    conn.close()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data.decode(errors="replace")


def set_phase(root, name, phase):
    path = os.path.join(root, "projects", name, "state", "status.json")
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    st["phase"] = phase
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f)


def bad_length(port, length):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(("POST /api/git/push HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-AAF-Request: control-room\r\n"
                  "Content-Type: application/json\r\nContent-Length: %s\r\n\r\n" % (port, length)).encode())
    try:
        return sock.recv(64).decode(errors="replace")
    except socket.timeout:
        return "timed out"
    finally:
        sock.close()


def writes(port, root):
    """Push and Pull, in the order of tests/test_git.py. Returns what each step gave."""
    remote = lambda n: gw.git(os.path.join(root, "remotes", n + ".git"), "log", "--format=%s", "main")
    info = lambda n: request(port, "GET", "/api/git?name=%s&fresh=1" % n)[1]
    out = []
    before = remote("example-done")
    out.append(("no header", request(port, "POST", "/api/git/push", {"name": "example-done"}, {"Content-Type": "application/json"})[0]))
    for extra in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Origin": "http://localhost:1"}):
        out.append(("foreign " + list(extra.values())[0], request(port, "POST", "/api/git/push", {"name": "example-done"}, dict(HEADER, **extra))[0]))
    out.append(("remote unchanged", remote("example-done") == before))
    out.append(("GET push", request(port, "GET", "/api/git/push?name=example-done")[0]))
    out.append(("reset", request(port, "POST", "/api/git/reset", {"name": "example-done"}, HEADER)[0]))
    out.append(("traversal", request(port, "POST", "/api/git/push", {"name": "../.."}, HEADER)[0]))
    out.append(("OPTIONS is not 204", request(port, "OPTIONS", "/api/git/push")[0] != 204))
    for length in ("-1", "abc", "99999"):
        status = bad_length(port, length)
        out.append(("length " + length, status.startswith("HTTP/1.0 4") or status.startswith("HTTP/1.1 4")))
    code, d = request(port, "POST", "/api/git/push", {"name": "example-done"}, dict(HEADER, Origin="http://127.0.0.1:%d" % port))
    out.append(("push", code, d.get("ok"), d.get("message", "").replace(root, "<root>")))
    out.append(("pushed", "Tidy up after review" in remote("example-done"), info("example-done").get("ahead")))
    set_phase(root, "image-classifier", "checking")
    code, d = request(port, "POST", "/api/git/pull", {"name": "image-classifier"}, HEADER)
    out.append(("pull while working", code, d.get("ok"), d.get("message")))
    out.append(("still behind", info("image-classifier").get("behind")))
    set_phase(root, "parser", "waiting")
    code, d = request(port, "POST", "/api/git/pull", {"name": "parser"}, HEADER)
    out.append(("pull", code, d.get("ok"), d.get("message", "").replace(root, "<root>")))
    out.append(("pulled", info("parser").get("behind")))
    return out


EXPECTED = {  # what tests/test_git.py expects of server.py
    "no header": 403, "foreign https://evil.example": 403, "foreign evil.example": 403,
    "foreign http://localhost:1": 403, "remote unchanged": True, "reset": 404, "traversal": 404,
    "OPTIONS is not 204": True, "length -1": True, "length abc": True, "length 99999": True,
}


def check_writes():
    roots = []
    try:
        py_root, _ = gw.make_workspace()
        rs_root, _ = gw.make_workspace()
        roots = [py_root, rs_root]
        httpd, _ = python_server(py_root)
        try:
            py = writes(httpd.server_address[1], py_root)
        finally:
            httpd.shutdown()
            httpd.server_close()
        s = app_server.Served(rs_root, clock=NOW)
        try:
            rs = writes(s.port, rs_root)
        finally:
            s.stop()
    finally:
        for r in roots:
            gw.remove_workspace(r)
    for p, r in zip(py, rs):
        if p != r:
            problems.append("write %s: server.py %r, Rust core %r" % (p[0], p[1:], r[1:]))
    got = {r[0]: r[1] for r in rs}
    for k, want in EXPECTED.items():
        if got.get(k) != want:
            problems.append("write %s: expected %r, Rust core gave %r" % (k, want, got.get(k)))
    if got.get("GET push") not in (404, 405):
        problems.append("write GET push: expected 404 or 405, got %r" % got.get("GET push"))
    rsd = {r[0]: r[1:] for r in rs}
    if rsd["push"][:2] != (200, True) or rsd["pushed"] != (True, 0):
        problems.append("write push did not send the commits: %r %r" % (rsd["push"], rsd["pushed"]))
    if rsd["pull while working"][:2] != (409, False) or rsd["still behind"] != (1,):
        problems.append("write pull while working was not refused: %r %r" % (rsd["pull while working"], rsd["still behind"]))
    if rsd["pull"][:2] != (200, True) or rsd["pulled"] != (0,):
        problems.append("write pull did not bring the newer commit: %r %r" % (rsd["pull"], rsd["pulled"]))
    return len(rs)


def check_no_git():
    src = os.path.join(PROJECT, "app", "src")
    files = [os.path.join(d, f) for d, _, fs in os.walk(src) for f in fs if f.endswith(".rs")]
    if not files:
        problems.append("no Rust source in app/src")
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if re.search(r'Command::new\(\s*"git(\.exe)?"\s*\)', text):
            problems.append("%s runs git itself; it must go through aaf.py" % os.path.relpath(path, PROJECT))
    return len(files)


def long_logs_workspace():
    """A copy of the fixtures where notes-app has long logs, so every limit is compared: 30 feed
    steps among quiet records and waits, the 12-run trend, 40 test runs, 60 events, 13+ tasks
    (the timeline's event window), 20 discarded drafts, 200 reviews."""
    import shutil
    import tempfile
    root = tempfile.mkdtemp(prefix="aaf-long-")
    shutil.copytree(os.path.join(PROJECT, "fixtures", "workspace", "projects"), os.path.join(root, "projects"))
    state = os.path.join(root, "projects", "notes-app", "state")

    def append(name, rows):
        with open(os.path.join(state, name), "a", encoding="utf-8", newline="") as f:
            for r in rows:
                f.write((json.dumps(r) if not isinstance(r, str) else r) + "\r\n")
    act = []
    for i in range(80):
        act.append({"ts": "2026-10-14T13:%02d:00+02:00" % (i % 60), "kind": "read", "text": "Reading f%d" % i, "tool_use_id": "t%d" % i})
        act.append({"ts": "2026-10-14T13:%02d:01+02:00" % (i % 60), "kind": "done", "text": "Finished", "tool_use_id": "t%d" % i, "quiet": True})
        if i % 9 == 0:
            act.append({"ts": "2026-10-14T13:%02d:02+02:00" % (i % 60), "kind": "waiting", "text": "Waiting for your permission in Claude Code"})
        if i % 13 == 0:
            act.append("not json")
    append("activity.jsonl", act)
    append("check_history.jsonl", [{"at": "2026-10-1%dT10:00:00+02:00" % (i % 10), "n_pass": i % 4, "n_total": 3}
                                   for i in range(50)] + [{"n_pass": "x", "n_total": 2}, [1], {"n_total": 0}])
    ev = []
    for h in range(16):
        ev.append({"ts": "2026-10-15T%02d:00:00+02:00" % (6 + h), "kind": "status", "text": "Planning: T%d" % h,
                   "phase": "planning", "iteration": 0, "task": "T%d" % h})
        ev.append({"ts": "2026-10-15T%02d:30:00+01:00" % (5 + h), "kind": "decision", "text": "Mixed offset %d" % h})
        ev.append({"ts": "2026-10-15T%02d:50:00+02:00" % (6 + h), "kind": "status", "text": "Done: T%d" % h,
                   "phase": "done", "iteration": 1, "task": "T%d" % h})
    append("events.jsonl", ev)
    append("discarded_drafts.jsonl", [{"id": "fix-%d" % i, "title": "Old %d" % i} for i in range(25)])
    append("review_history.jsonl", [{"at": "2026-10-15T10:%02d:00+02:00" % (i % 60), "verdict": "fail" if i % 3 else "pass",
                                     "summary": ["progress note missing", "a crash", "weakened a test", "", "layout on phone"][i % 5]}
                                    for i in range(210)])
    return root


def check_drive_names():
    """Stricter than server.py (decision recorded): a plot name with a drive (`C:probe.png`) would read
    an image from the core's working folder on Windows; the core refuses it."""
    import tempfile
    cwd = tempfile.mkdtemp(prefix="aaf-cwd-")
    drive = os.path.splitdrive(cwd)[0] or "C:"
    try:
        with open(os.path.join(cwd, "probe.png"), "wb") as f:
            f.write(b"not a plot")
        s = app_server.Served(os.path.join(PROJECT, "fixtures", "workspace"), cwd=cwd)
        try:
            for name in (drive + "probe.png", drive.replace(":", "%3A") + "probe.png", "probe.png"):
                code = fetch(s.base, "/plot?project=example-done&file=" + name)[0]
                if code != 404:
                    problems.append("plot %s: %s, expected 404 (outside plots/)" % (name, code))
        finally:
            s.stop()
    finally:
        import shutil
        shutil.rmtree(cwd, ignore_errors=True)


def main():
    try:
        app_server.build()
    except RuntimeError as e:
        print("FAIL: the Rust core could not be built:", e)
        return 1
    n = compare_workspace("fixtures", os.path.join(PROJECT, "fixtures", "workspace"))
    n += compare_workspace("first-run", os.path.join(PROJECT, "fixtures", "first-run"))
    root = long_logs_workspace()
    try:
        n += compare_workspace("long logs", root)
    finally:
        gw.remove_workspace(root)
    root, _ = gw.make_workspace()
    try:
        gw.code_repo(root, "scheduler")
        n += compare_workspace("git", root)
    finally:
        gw.remove_workspace(root)
    w = check_writes()
    check_drive_names()
    f = check_no_git()
    if problems:
        print("FAIL: %d difference(s) between server.py and the Rust core:" % len(problems))
        for p in problems[:60]:
            print("  -", p)
        return 1
    print("OK: %d requests answered the same on four workspaces, %d push/pull steps as expected, "
          "%d source files without a git command" % (n, w, f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
