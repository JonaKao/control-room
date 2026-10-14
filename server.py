#!/usr/bin/env python3
"""Agent Control Room: local dashboard for the Agentic AI Framework.

  python3 projects/control-room/server.py [--port 8765] [--root WORKSPACE]

Then open http://localhost:8765. Reads <workspace>/projects/*/state and */plots;
writes nothing. Standard library only. --root points it at another workspace
(the checks use this to render fixture data).
"""

import argparse
import json
import mimetypes
import os
import re
import sys
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
        "plots": plots,
        "drafts": drafts(name),
        "discarded": read_jsonl(os.path.join(pdir, "state", "discarded_drafts.jsonl"), last=20),
    }


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
