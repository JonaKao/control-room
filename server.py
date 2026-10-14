#!/usr/bin/env python3
"""Agent Control Room: local dashboard for the Agentic AI Framework.

  python3 projects/control-room/server.py [--port 8765] [--root WORKSPACE]

Then open http://localhost:8765. Reads <workspace>/projects/*/state and */plots.
The only thing it changes is Git: Push and Pull on the page run
`framework/aaf.py git push|pull <project>` (never git itself), and only for requests
that come from the page on this machine. Standard library only. --root points it at
another workspace (the checks use this to render fixture data).
"""

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))


def find_root(start):
    """The workspace is the nearest folder above this file that has framework/aaf.py."""
    d = start
    while True:
        if os.path.isfile(os.path.join(d, "framework", "aaf.py")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.dirname(os.path.dirname(start))
        d = parent


ROOT = find_root(HERE)
PROJECTS = os.path.join(ROOT, "projects")


def set_root(root):
    global ROOT, PROJECTS
    ROOT = os.path.abspath(root)
    PROJECTS = os.path.join(ROOT, "projects")
# Phases in which the agent is changing files; pulling then would pull the rug from under it.
WORKING = ("planning", "implementing", "checking", "reviewing", "fixing")
WRITE_HEADER = ("X-AAF-Request", "control-room")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1")
GIT_CACHE_S = 15
ACTIVITY_LAST = 30  # steps of the live feed sent to the page
_git_cache = {}
_git_locks = {}
_git_info_locks = {}
_git_locks_guard = threading.Lock()
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PLOT_EXT = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp")


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_text(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def read_jsonl(path, last=None):
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out[-last:] if last else out


def read_jsonl_tail(path, last, chunk=65536, limit=262144):
    """The newest `last` JSON objects of a log that only grows at the end, without reading all of it.
    Reads backwards in chunks until enough complete lines are found, but never more than `limit`
    bytes. Broken lines are skipped."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos, buf = f.tell(), b""
            while pos > 0 and buf.count(b"\n") <= last and len(buf) < limit:
                step = min(chunk, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
    except OSError:
        return []
    lines = buf.split(b"\n")
    if pos > 0:
        lines = lines[1:]  # the first line may be cut off
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out[-last:]


def parse_decisions(md):
    items = []
    for block in re.split(r"^## ", md, flags=re.M)[1:]:
        head, _, body = block.partition("\n")
        m = re.match(r"(\d{4}-\d{2}-\d{2}):\s*(.*)", head.strip())
        date, title = (m.group(1), m.group(2)) if m else ("", head.strip())
        items.append({"date": date, "title": title, "body": body.strip()})
    return items


def project_names():
    if not os.path.isdir(PROJECTS):
        return []
    return sorted(p for p in os.listdir(PROJECTS)
                  if NAME_RE.match(p) and os.path.isdir(os.path.join(PROJECTS, p)))


def drafts(name):
    root = os.path.join(PROJECTS, name, "state", "drafts")
    out = []
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            meta = read_json(os.path.join(root, d, "meta.json"), None)
            if meta:
                out.append(meta)
    return out


def summary(name):
    pdir = os.path.join(PROJECTS, name)
    st = read_json(os.path.join(pdir, "state", "status.json"), {}) or {}
    ck = read_json(os.path.join(pdir, "state", "checks.json"), {}) or {}
    rv = read_json(os.path.join(pdir, "state", "review.json"), {}) or {}
    meta = read_json(os.path.join(pdir, "project.json"), {}) or {}
    checks = ck.get("checks", [])
    return {
        "name": name,
        "description": meta.get("description", ""),
        "phase": st.get("phase", "idle"),
        "task": st.get("task", ""),
        "updated": st.get("updated", ""),
        "checks_pass": sum(1 for c in checks if c.get("passed")),
        "checks_total": len(checks),
        "verdict": rv.get("verdict"),
        "drafts": len(drafts(name)),
        "activity": (read_jsonl_tail(os.path.join(pdir, "state", "activity.jsonl"), 1) or [None])[-1],
    }


def detail(name):
    pdir = os.path.join(PROJECTS, name)
    plots_dir = os.path.join(pdir, "plots")
    plots = []
    if os.path.isdir(plots_dir):
        for fn in os.listdir(plots_dir):
            if fn.lower().endswith(PLOT_EXT):
                plots.append({"file": fn, "mtime": os.path.getmtime(os.path.join(plots_dir, fn))})
    plots.sort(key=lambda p: -p["mtime"])
    return {
        "summary": summary(name),
        "meta": read_json(os.path.join(pdir, "project.json"), {}) or {},
        "status": read_json(os.path.join(pdir, "state", "status.json"), {}) or {},
        "checks": read_json(os.path.join(pdir, "state", "checks.json"), None),
        "check_history": read_jsonl(os.path.join(pdir, "state", "check_history.jsonl"), last=40),
        "review": read_json(os.path.join(pdir, "state", "review.json"), None),
        "decisions": parse_decisions(read_text(os.path.join(pdir, "state", "decisions.md"))),
        "progress": read_text(os.path.join(pdir, "state", "progress.md")),
        "events": read_jsonl(os.path.join(pdir, "state", "events.jsonl"), last=60),
        "activity": read_jsonl_tail(os.path.join(pdir, "state", "activity.jsonl"), ACTIVITY_LAST),
        "plots": plots,
        "drafts": drafts(name),
        "discarded": read_jsonl(os.path.join(pdir, "state", "discarded_drafts.jsonl"), last=20),
    }


def aaf(*args, timeout=60):
    """Run the served workspace's framework/aaf.py. Returns (exit code, stdout, stderr)."""
    path = os.path.join(ROOT, "framework", "aaf.py")
    if not os.path.isfile(path):
        return None, "", "framework/aaf.py not found"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        proc = subprocess.run([sys.executable, path] + list(args), cwd=ROOT, capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %d s" % timeout
    return proc.returncode, proc.stdout, proc.stderr


def git_info(name, fresh=False):
    """`aaf.py git info <name> --fetch`, cached briefly so polling does not hammer GitHub.
    Requests arriving while one is running wait for it and share its answer."""
    asked = time.time()
    hit = _git_cache.get((ROOT, name))
    if hit and not fresh and asked - hit["finished"] < GIT_CACHE_S:
        return hit["data"]
    if not os.path.isfile(os.path.join(ROOT, "framework", "aaf.py")):
        return {"available": False, "repo": False}
    with _git_locks_guard:
        lock = _git_info_locks.setdefault((ROOT, name), threading.Lock())
    with lock:
        hit = _git_cache.get((ROOT, name))
        # A run that started after we asked is always good enough, however long it took.
        # Otherwise a plain request may still use an entry that finished recently; a fresh one may not.
        if hit and (hit["started"] >= asked or not fresh and time.time() - hit["finished"] < GIT_CACHE_S):
            return hit["data"]
        return _git_info_run(name)


def _git_info_run(name):
    started = time.time()  # a run that began before a push never counts as fresh
    code, out, err = aaf("git", "info", name, "--fetch", timeout=30)
    try:
        data = json.loads(out) if code == 0 else None
    except ValueError:
        data = None
    if data is None:
        data = {"available": True, "repo": False, "error": (err or out).strip()[-400:]}
    data.setdefault("available", True)
    _git_cache[(ROOT, name)] = {"started": started, "finished": time.time(), "data": data}
    return data


def git_action(name, action):
    """Push or pull through aaf.py. Returns (http code, result)."""
    st = read_json(os.path.join(PROJECTS, name, "state", "status.json"), {}) or {}
    if action == "pull" and st.get("phase") in WORKING:
        return 409, {"ok": False, "message": "The agent is working on this project right now. "
                                             "Pull again once it has finished or stopped."}
    with _git_locks_guard:
        lock = _git_locks.setdefault((ROOT, name), threading.Lock())
    if not lock.acquire(blocking=False):
        return 409, {"ok": False, "message": "A push or pull for this project is already running."}
    try:
        code, out, err = aaf("git", action, name, timeout=120)
    finally:
        lock.release()
    _git_cache.pop((ROOT, name), None)
    text = (out + "\n" + err).strip()
    text = re.sub(r"^error: ", "", text)
    if code == 0:
        return 200, {"ok": True, "message": text or ("Pushed." if action == "push" else "Pulled.")}
    return 502, {"ok": False, "message": text[-600:] or "%s failed" % action}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        name = (q.get("name") or q.get("project") or [""])[0]
        if url.path in ("/", "/index.html"):
            return self.send(200, read_text(os.path.join(HERE, "index.html")), "text/html; charset=utf-8")
        if url.path == "/api/projects":
            return self.json([summary(n) for n in project_names()])
        if url.path == "/api/project":
            if name not in project_names():
                return self.json({"error": "unknown project"}, 404)
            return self.json(detail(name))
        if url.path == "/api/git":
            if name not in project_names():
                return self.json({"error": "unknown project"}, 404)
            return self.json(git_info(name, fresh=bool(q.get("fresh"))))
        if url.path == "/plot":
            fn = (q.get("file") or [""])[0]
            if name not in project_names() or "/" in fn or "\\" in fn or fn.startswith(".") \
                    or not fn.lower().endswith(PLOT_EXT):
                return self.send(404, "not found", "text/plain")
            path = os.path.join(PROJECTS, name, "plots", fn)
            if not os.path.isfile(path):
                return self.send(404, "not found", "text/plain")
            with open(path, "rb") as f:
                return self.send(200, f.read(), mimetypes.guess_type(fn)[0] or "application/octet-stream")
        self.send(404, "not found", "text/plain")


    def from_page(self):
        """Only the page itself may ask for a change: same machine, our header, our host and origin."""
        if self.client_address[0] not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return False
        if self.headers.get(WRITE_HEADER[0]) != WRITE_HEADER[1]:
            return False
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").rsplit(":", 1)
        if host[0] not in LOCAL_HOSTS or (len(host) > 1 and host[1] != str(port)):
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in ["http://%s:%d" % (h, port) for h in ("localhost", "127.0.0.1", "[::1]")]:
            return False
        return True

    def do_POST(self):
        url = urlparse(self.path)
        m = re.match(r"^/api/git/(push|pull)$", url.path)
        if not m:
            return self.send(404, "not found", "text/plain")
        if not self.from_page():
            return self.json({"ok": False, "message": "Only the Control Room page on this computer may do this."}, 403)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 4096:
            # Never read an unbounded or negative length: that would block this thread.
            self.close_connection = True
            return self.json({"ok": False, "message": "bad request"}, 400)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            name = body.get("name", "") if isinstance(body, dict) else ""
        except (ValueError, OSError):
            return self.json({"ok": False, "message": "bad request"}, 400)
        if name not in project_names():
            return self.json({"ok": False, "message": "unknown project"}, 404)
        code, result = git_action(name, m.group(1))
        return self.json(result, code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--root", help="workspace folder to read (default: the one this file lives in)")
    a = ap.parse_args()
    if a.root:
        set_root(a.root)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("Dashboard running at http://localhost:%d  (Ctrl+C to stop)" % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
