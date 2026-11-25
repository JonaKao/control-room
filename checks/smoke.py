"""Smoke check of the core, for places without the framework (GitHub Actions): start
`control-room serve` on the fixtures and check every answer that does not need framework/aaf.py.

    python3 checks/smoke.py [path to the control-room program]

Without a path it builds the app (debug) with cargo first, like the other checks. Standard library only.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
NAMES = ["api-client", "brand-new", "data-pipeline", "example-done", "image-classifier", "notes-app", "parser",
         "scheduler", "web-scraper"]
problems = []


def get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=60) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def post(base, path, body, header=True):
    port = base.rsplit(":", 1)[1]
    headers = {"Content-Type": "application/json", "Host": "127.0.0.1:" + port}
    if header:
        headers["X-AAF-Request"] = "control-room"
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def expect(what, got, want):
    if got != want:
        problems.append("%s: got %r, expected %r" % (what, got, want))


def main():
    if len(sys.argv) > 1:
        exe = os.path.abspath(sys.argv[1])
    else:
        sys.path.insert(0, HERE)
        import app_server
        exe = app_server.build()
    config = tempfile.mkdtemp(prefix="aaf-smoke-")
    proc = subprocess.Popen([exe, "serve", "--root", FIXTURES, "--port", "0", "--config", config],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().strip()
        if not line.startswith("Serving on "):
            print("FAIL: control-room serve did not start: %r %s" % (line, proc.stderr.read() if proc.poll() is not None else ""))
            return 1
        base = line[len("Serving on "):]
        code, ctype, body = get(base, "/")
        expect("page", (code, "text/html" in ctype, b"<title>Agent Control Room</title>" in body), (200, True, True))
        projects = json.loads(get(base, "/api/projects")[2])
        expect("projects", sorted(p["name"] for p in projects), NAMES)
        detail = json.loads(get(base, "/api/project?name=parser")[2])
        expect("parser waits for a decision", (detail["status"].get("phase"), [d["id"] for d in detail["drafts"]]), ("waiting", ["fix-1"]))
        web = json.loads(get(base, "/api/project?name=web-scraper")[2])
        expect("web-scraper's newest step", web["summary"]["activity"]["kind"], "waiting")
        record = json.loads(get(base, "/api/project?name=api-client")[2])["record"]
        expect("api-client's reasons", [(g["key"], g["count"]) for g in record["reasons"]],
               [("progress", 3), ("weakened", 1), ("coverage", 1), ("bug", 1)])
        expect("plot", get(base, "/plot?project=example-done&file=loss.svg")[:2], (200, "image/svg+xml"))
        for path in ("/plot?project=example-done&file=../project.json", "/plot?project=../..&file=loss.svg",
                     "/plot?project=example-done&file=C:loss.svg", "/api/project?name=..", "/api/project?name=nope",
                     "/api/git?name=../..", "/nothing"):
            expect("refused " + path, get(base, path)[0], 404)
        expect("git without the framework", json.loads(get(base, "/api/git?name=example-done")[2]).get("available"), False)
        ws = json.loads(get(base, "/api/workspaces")[2])
        expect("workspaces", (len(ws["workspaces"]), ws["can_pick"]), (1, False))
        expect("events", json.loads(get(base, "/api/events")[2]), {"events": []})
        expect("write without the page's header", post(base, "/api/git/push", {"name": "example-done"}, header=False), 403)
        expect("unknown write", post(base, "/api/git/reset", {"name": "example-done"}), 404)
        expect("pull while the agent works", post(base, "/api/git/pull", {"name": "image-classifier"}), 409)
    finally:
        proc.kill()
        proc.wait()
    if problems:
        print("FAIL: smoke check:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: serve answers the page, the projects, a detail, plots and refusals as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
