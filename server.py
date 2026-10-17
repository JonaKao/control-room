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
from datetime import datetime
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
_stats_cache = {}
_files_cache = {}
FILES_CACHE_S = 30
STATS_TASKS_EVENTS = 400  # events of the shown tasks sent along, so the page can say what happened in a segment
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
        "trend": trend(pdir),
        "plan": plan_progress(pdir),
    }


TREND_RUNS = 12  # test runs in the project list's tiny trend line


def trend(pdir):
    """Share of tests passing in each of the latest test runs, oldest first, for the project list."""
    out = []
    for h in read_jsonl(os.path.join(pdir, "state", "check_history.jsonl"), last=TREND_RUNS):
        try:
            total = int(h.get("n_total") or 0)
            out.append(round(int(h.get("n_pass") or 0) / total, 3) if total else 0.0)
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def plan_progress(pdir):
    """How many of the current plan's steps are done (state/plan.json, written by aaf.py plan), or None."""
    p = read_json(os.path.join(pdir, "state", "plan.json"), None)
    steps = p.get("steps") if isinstance(p, dict) else None
    if not isinstance(steps, list) or not steps:
        return None
    steps = [x for x in steps if isinstance(x, dict)]
    done = sum(1 for x in steps if x.get("done_at"))
    current = next((str(x.get("text", "")) for x in steps if not x.get("done_at")), "")
    return {"done": done, "total": len(steps), "current": current, "task": str(p.get("task", "")),
            "steps": [{"text": str(x.get("text", "")), "done": bool(x.get("done_at"))} for x in steps[:40]]}


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
        "tasks": task_stats(name),
        "record": record(name),
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


def stats_aaf_path():
    """The aaf.py whose task_stats() derives the task timeline: the served workspace's, or, for a
    workspace without one (the fixtures), the one of the workspace this server lives in."""
    for root in (ROOT, find_root(HERE)):
        path = os.path.join(root, "framework", "aaf.py")
        if os.path.isfile(path):
            return path
    return None


_STATS_CODE = ("import importlib.util, json, sys\n"
               "spec = importlib.util.spec_from_file_location('aaf', sys.argv[1])\n"
               "aaf = importlib.util.module_from_spec(spec); spec.loader.exec_module(aaf)\n"
               "print(json.dumps(aaf.task_stats(sys.argv[2])))\n")


def _stats_run(pdir):
    """aaf.task_stats(<project folder>), i.e. what `aaf.py stats <name>` prints, in a subprocess."""
    path = stats_aaf_path()
    if not path:
        return {"available": False, "summary": {}, "tasks": [], "error": "framework/aaf.py not found"}
    try:
        proc = subprocess.run([sys.executable, "-c", _STATS_CODE, path, pdir], capture_output=True,
                              text=True, timeout=20, cwd=pdir)
        data = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError):
        data = None
    if not isinstance(data, dict):
        return {"available": False, "summary": {}, "tasks": [], "error": "could not read the task history"}
    data["available"] = True
    return data


def task_stats(name):
    """The task timeline, recomputed only when the project's event log changes."""
    pdir = os.path.join(PROJECTS, name)
    events = os.path.join(pdir, "state", "events.jsonl")
    try:
        st = os.stat(events)
        sig = (st.st_size, st.st_mtime_ns)
    except OSError:
        sig = None
    if stats_aaf_path() is None:
        return {"available": False, "summary": {}, "tasks": [], "events": []}
    hit = _stats_cache.get((ROOT, name))
    if hit and hit[0] == sig:
        return hit[1]
    data = _stats_run(pdir)
    # The events inside the shown tasks, so the page can say what happened in each segment.
    # Times are compared as times: the log may mix time zone offsets.
    first = _when(data["tasks"][-12]["start"]) if len(data.get("tasks") or []) > 12 else None
    rows = [e for e in read_jsonl(events) if first is None or (_when(e.get("ts")) or first) >= first]
    data["events"] = [{k: e[k] for k in ("ts", "kind", "text", "verdict", "passed") if k in e}
                      for e in rows[-STATS_TASKS_EVENTS:]]
    if data["available"]:  # a failed run is tried again on the next request
        _stats_cache[(ROOT, name)] = (sig, data)
    return data


# Why a review rejected work, sorted into a few themes by the words in its one-line summary.
# Each theme: key, plain label, words that point to it, words of a definition-of-done item that
# covers it (None: no usual item), and what the human could sharpen when it keeps coming back.
REASONS = [
    ("progress", "The progress note was not updated",
     r"progress(\.md| note)|what is next|what changed", r"progress",
     "Say in the definition of done that the progress note must say what changed and what is next."),
    ("weakened", "A test was weakened, skipped or removed",
     r"weaken|skip|loosen|disabl|removed (a |the )?(test|check)|threshold", r"weaken|skipp",
     "Repeat in the project instructions that tests and thresholds must never be loosened."),
    ("coverage", "The task's success was not covered by a test",
     r"not covered|no (test|check) (for|covers)|untested|by hand|manual", r"covered by a check|manual",
     "Ask in the definition of done for a check that proves the task, written before the change."),
    ("failing", "Tests failed or were not run",
     r"\b(checks?|tests?) (fail|not run|red|broken)|failing (checks?|tests?)", r"check.*pass",
     "Ask in the project instructions to run every test before asking for a review."),
    ("bug", "A bug in the change",
     r"\bbug|crash|\bwrong\b|incorrect|regress|\brace\b|leak|exception", None,
     "Describe the tricky cases in the project instructions, or add a test for them."),
    ("screens", "Screenshots or plots were not looked at",
     r"screenshot|\bplots?\b|not (opened|inspected)", r"screenshot|plot",
     "Ask in the definition of done to open and describe the screenshots or plots."),
    ("wording", "Unclear wording or jargon",
     r"jargon|plain (words|language)|wording|internal (terms?|names?)", r"plain language|wording",
     "Give examples of the wording you want in the project instructions."),
    ("layout", "Layout problems on small screens",
     r"\bphone|mobile|sideways|overflow|layout", r"phone|sideways",
     "Name the screen sizes that must work in the definition of done."),
    ("scope", "Part of the task was left out",
     r"missing|not implemented|incomplete|does not (do|meet)|not done", None,
     "Write the task with a list of what must be there when it is done."),
]
OTHER = ("other", "Other reasons", "Read these summaries: if one keeps coming back, add it to the definition of done.")


def done_items(name):
    """The checklist items of a project's definition of done (DONE.md), as plain text."""
    md = read_text(os.path.join(PROJECTS, name, "DONE.md"))
    return [re.sub(r"`", "", m.group(1)).strip() for m in re.finditer(r"^\s*[-*]\s+\[[ xX]\]\s+(.+)$", md, flags=re.M)]


def review_reasons(rows, items=None, items_by_project=None):
    """Failed reviews grouped by theme, most common first ('other' last). `rows` are review history
    entries (optionally with 'project'); `items` is the definition of done to match each theme to, or, across
    projects, `items_by_project` gives each project's (then 'covered_in' names the projects whose
    definition of done already covers the theme). 'rejections' is the number of failed reviews: one
    summary can name several themes, so the counts may add up to more."""
    groups, rejections = {}, 0
    for r in rows:
        if str(r.get("verdict", "")).lower() != "fail":
            continue
        rejections += 1
        text = str(r.get("summary") or "")
        keys = [k for k, _, words, *_ in REASONS if re.search(words, text, re.I)] or [OTHER[0]]
        for k in keys:
            groups.setdefault(k, []).append({key: r[key] for key in ("at", "summary", "project") if key in r})
    out = []
    for key, label, _, done_words, advice in REASONS + [(OTHER[0], OTHER[1], None, None, OTHER[2])]:
        if key not in groups:
            continue
        ex = groups[key]
        covers = lambda its: next((i for i in (its or []) if done_words and re.search(done_words, i, re.I)), None)
        projects = sorted({e["project"] for e in ex if "project" in e})
        out.append({"key": key, "label": label, "count": len(ex), "advice": advice, "done_item": covers(items),
                    "covered_in": [p for p in projects if covers((items_by_project or {}).get(p))],
                    "projects": projects, "rejections": rejections, "examples": ex[::-1]})
    out.sort(key=lambda g: (g["key"] == OTHER[0], -g["count"]))
    return out


def record(name):
    """The project's track record: its review history and why reviews rejected work.
    The task numbers come with `tasks` (aaf.py task_stats)."""
    rows = read_jsonl(os.path.join(PROJECTS, name, "state", "review_history.jsonl"))
    return {"reviews": rows[-200:], "reasons": review_reasons(rows, done_items(name))}


TASK_KEYS = ("task", "start", "end", "outcome", "attempts", "first_try", "reviews", "drafts", "times_stuck")


def workspace_record():
    """Every project's track record side by side, and the most common reasons across all of them."""
    projects, rows, available = [], [], stats_aaf_path() is not None
    for name in project_names():
        st = task_stats(name)
        hist = read_jsonl(os.path.join(PROJECTS, name, "state", "review_history.jsonl"))
        rows += [dict(r, project=name) for r in hist]
        projects.append({"name": name, "summary": st.get("summary") or {},
                         "tasks": [{k: t.get(k) for k in TASK_KEYS} for t in st.get("tasks") or []]})
    items = {p["name"]: done_items(p["name"]) for p in projects}
    return {"available": available, "projects": projects, "reasons": review_reasons(rows, items_by_project=items)}


def _when(ts):
    """An ISO time stamp as seconds since the epoch, or None."""
    try:
        d = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return d.timestamp() if d.tzinfo else None


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


def git_files(name, fresh=False):
    """`aaf.py git files <name>` for the change map, cached briefly like the Git info."""
    if not os.path.isfile(os.path.join(ROOT, "framework", "aaf.py")):
        return {"available": False, "repo": False, "files": []}
    hit = _files_cache.get((ROOT, name))
    if hit and not fresh and time.time() - hit[0] < FILES_CACHE_S:
        return hit[1]
    code, out, err = aaf("git", "files", name, timeout=30)
    try:
        data = json.loads(out) if code == 0 else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {"available": True, "repo": False, "files": [], "error": (err or out).strip()[-400:]}
    data["available"] = True
    _files_cache[(ROOT, name)] = (time.time(), data)
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
    _files_cache.pop((ROOT, name), None)
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
        if url.path == "/api/record":
            return self.json(workspace_record())
        if url.path == "/api/project":
            if name not in project_names():
                return self.json({"error": "unknown project"}, 404)
            return self.json(detail(name))
        if url.path == "/api/git":
            if name not in project_names():
                return self.json({"error": "unknown project"}, 404)
            return self.json(git_info(name, fresh=bool(q.get("fresh"))))
        if url.path == "/api/files":
            if name not in project_names():
                return self.json({"error": "unknown project"}, 404)
            return self.json(git_files(name, fresh=bool(q.get("fresh"))))
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
