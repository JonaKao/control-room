"""Build a throwaway workspace with real Git repositories, for the Git tests and checks.

Nothing is committed into fixtures: every call creates a fresh temporary folder with
- framework/aaf.py (a copy of the real one, so it treats the temp folder as its workspace)
- projects/<name>/ copied from the fixtures, each made into a Git repository
- remotes/<name>.git, a bare repository standing in for GitHub

make_workspace() returns (root, info) where info[name] describes the state it set up.
"""
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
FIXTURES = os.path.join(PROJECT, "fixtures", "workspace", "projects")
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="Agent", GIT_AUTHOR_EMAIL="agent@example.com",
               GIT_COMMITTER_NAME="Agent", GIT_COMMITTER_EMAIL="agent@example.com",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")


def find_aaf():
    d = PROJECT
    while d != os.path.dirname(d):
        path = os.path.join(d, "framework", "aaf.py")
        if os.path.isfile(path):
            return path
        d = os.path.dirname(d)
    raise RuntimeError("framework/aaf.py not found above " + PROJECT)


def git(cwd, *args, stdin=None):
    return subprocess.run(["git"] + list(args), cwd=cwd, env=GIT_ENV, input=stdin, text=True,
                          capture_output=True, check=True).stdout


def commit(cwd, subject, body="", trailers=None, touch=None):
    path = os.path.join(cwd, touch or "work.txt")
    with open(path, "a") as f:
        f.write(subject + "\n")
    git(cwd, "add", "-A")
    msg = subject + "\n\n" + (body + "\n\n" if body else "")
    if trailers:
        msg += "\n".join("%s: %s" % kv for kv in trailers.items()) + "\n"
    git(cwd, "commit", "-q", "-F", "-", stdin=msg)


# Commits, oldest first: (subject, body, trailers). Covers each colour the timeline uses.
HISTORY = [
    ("Start project", "", None),
    ("Add the parser", "Decisions:\n- Use a hand-written lexer\n  Regex was too slow on long lines.",
     {"Agent-Project": "demo", "Checks": "2/2", "Review": "pass", "Agent-Attempts": "2"}),
    ("Try multi-line traces", "", {"Agent-Project": "demo", "Checks": "1/2", "Review": "fail"}),
    ("Fix multi-line traces", "Decisions:\n- Join continuation lines first",
     {"Agent-Project": "demo", "Checks": "2/2", "Agent-Attempts": "3"}),
    ("Tidy up after review", "", {"Agent-Project": "demo", "Checks": "2/2", "Review": "pass"}),
]


def _repo(root, name, history, push_upto):
    """Make projects/<name> a repo with `history`; push the first `push_upto` commits."""
    pdir = os.path.join(root, "projects", name)
    remote = os.path.join(root, "remotes", name + ".git")
    git(root, "init", "-q", "--bare", "-b", "main", remote)
    git(pdir, "init", "-q", "-b", "main")
    with open(os.path.join(pdir, ".gitignore"), "w") as f:
        f.write("state/status.json\nstate/checks.json\nstate/check_history.jsonl\nstate/events.jsonl\n"
                "state/git.json\nstate/drafts/\n")
    git(pdir, "remote", "add", "origin", remote)
    for i, (subject, body, trailers) in enumerate(history):
        commit(pdir, subject, body, trailers)
        if i + 1 == push_upto:
            git(pdir, "push", "-q", "-u", "origin", "main")
    return pdir, remote


def add_remote_commit(root, name, subject):
    """Someone else pushes to the remote, so the local copy falls behind."""
    other = os.path.join(root, "other-" + name)
    if not os.path.isdir(other):
        git(root, "clone", "-q", os.path.join(root, "remotes", name + ".git"), other)
    else:
        git(other, "pull", "-q", "--ff-only")
    commit(other, subject, touch="other.txt")
    git(other, "push", "-q", "origin", "main")


def make_workspace(projects=("example-done", "image-classifier", "parser")):
    """example-done: 2 commits not on GitHub yet; parser: 1 newer commit on GitHub and an
    uncommitted file; image-classifier: in sync while the agent is working; others: no Git."""
    root = tempfile.mkdtemp(prefix="aaf-git-")
    os.makedirs(os.path.join(root, "framework"))
    os.makedirs(os.path.join(root, "remotes"))
    shutil.copy(find_aaf(), os.path.join(root, "framework", "aaf.py"))
    shutil.copytree(FIXTURES, os.path.join(root, "projects"))
    info = {}
    if "example-done" in projects:
        _repo(root, "example-done", HISTORY, push_upto=3)
        info["example-done"] = {"commits": len(HISTORY), "ahead": 2, "behind": 0, "changed": 0}
    if "parser" in projects:
        pdir, _ = _repo(root, "parser", HISTORY[:2], push_upto=2)
        add_remote_commit(root, "parser", "Fix typo in the README")
        git(pdir, "fetch", "-q")
        with open(os.path.join(pdir, "notes.txt"), "w") as f:
            f.write("not committed yet\n")
        info["parser"] = {"commits": 2, "ahead": 0, "behind": 1, "changed": 1}
    if "image-classifier" in projects:
        pdir, _ = _repo(root, "image-classifier", HISTORY[:2], push_upto=2)
        add_remote_commit(root, "image-classifier", "Newer work on GitHub")
        git(pdir, "fetch", "-q")
        info["image-classifier"] = {"commits": 2, "ahead": 0, "behind": 1, "changed": 0}
    return root, info


def remove_workspace(root):
    shutil.rmtree(root, ignore_errors=True)


# A small code project for the change map: (path, size in bytes, how many commits change it).
CODE_TREE = [
    ("scheduler/core.py", 6200, 9), ("scheduler/queue.py", 3100, 5), ("scheduler/clock.py", 1500, 3),
    ("scheduler/__init__.py", 60, 1), ("tests/test_core.py", 4100, 6), ("tests/test_queue.py", 2000, 2),
    ("README.md", 2600, 2), ("config/defaults.yaml", 700, 1), ("plots/latency.csv", 1800, 2),
]


def code_repo(root, name="scheduler"):
    """Make projects/<name> a repository with a code tree whose files changed unevenly.
    Returns {path: (commits, last subject)} for the code files."""
    pdir = os.path.join(root, "projects", name)
    git(pdir, "init", "-q", "-b", "main")
    rounds = max(n for _, _, n in CODE_TREE)
    want = {}
    for r in range(rounds):
        subject = "Round %d: %s" % (r + 1, "start the project" if r == 0 else "work on the scheduler")
        for path, size, n in CODE_TREE:
            if r >= n:
                continue
            full = os.path.join(pdir, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            # The first commit writes most of the file; later ones grow it a little.
            body = "x" * max(0, size - 40 * (n - 1) - 30) + "\n" if r == 0 else ""
            with open(full, "a") as f:
                f.write(body + ("# change %02d %s\n" % (r + 1, "." * 21))[:40])
            want[path] = (n, subject)
        git(pdir, "add", "-A")
        git(pdir, "commit", "-q", "-m", subject)
    return want
