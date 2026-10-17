"""README.md explains the control room to someone who has never seen it. It follows the workspace
template (template/README.md), keeps the generated sections that `aaf.py git commit` refreshes, names
every part of the page by the title the page itself shows, and only points to files that exist."""
import os
import re
import subprocess
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(PROJECT))
TEMPLATE_HEADINGS = ["What it does", "How to run", "How it is built", "How it is checked", "History"]
# The parts of the page, by the title the page shows for each.
PAGE_PARTS = ["At a glance", "Step by step", "Where the time went", "Track record",
              "Saved versions (Git)", "Where the agent works"]


def read(path):
    with open(path) as f:
        return f.read()


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        path = os.path.join(PROJECT, "README.md")
        self.assertTrue(os.path.exists(path), "projects/control-room/README.md is missing")
        self.text = read(path)
        self.headings = [m.group(1).strip() for m in re.finditer(r"^## (.+)$", self.text, flags=re.M)]

    def section(self, heading):
        m = re.search(r"^## %s\s*$(.*?)(?=^## |\Z)" % re.escape(heading), self.text, flags=re.M | re.S)
        self.assertIsNotNone(m, "no section '## %s'" % heading)
        return m.group(1)

    def test_starts_with_the_project_name(self):
        self.assertTrue(self.text.startswith("# control-room\n"), "the first line should be '# control-room'")

    def test_template_sections_in_order(self):
        found = [h for h in self.headings if h in TEMPLATE_HEADINGS]
        self.assertEqual(found, TEMPLATE_HEADINGS, "template sections missing or out of order")

    def test_no_template_leftovers(self):
        for left in ("{{NAME}}", "{{DESCRIPTION}}", "<!-- Written by the agent", "<!-- Exact commands",
                     "<!-- The main parts"):
            self.assertNotIn(left, self.text, "template placeholder left in: %s" % left)

    def test_generated_markers_kept_in_their_sections(self):
        for name, heading in (("checks", "How it is checked"), ("history", "History")):
            body = self.section(heading)
            start, end = "<!-- aaf:%s:start -->" % name, "<!-- aaf:%s:end -->" % name
            self.assertEqual(self.text.count(start), 1, "%s must appear exactly once" % start)
            self.assertEqual(self.text.count(end), 1, "%s must appear exactly once" % end)
            self.assertLess(body.find(start), body.find(end), "%s markers out of place" % name)
            self.assertNotEqual(body.find(start), -1, "%s markers belong under '## %s'" % (name, heading))

    def test_links_the_roadmap(self):
        self.assertRegex(self.text, r"\]\(ROADMAP\.md\)", "README.md should link ROADMAP.md")
        self.assertTrue(os.path.exists(os.path.join(PROJECT, "ROADMAP.md")))

    def test_names_every_part_of_the_page(self):
        page = read(os.path.join(PROJECT, "index.html"))
        what = self.section("What it does")
        for part in PAGE_PARTS:
            self.assertIn(part, page, "the page no longer shows '%s'; update PAGE_PARTS and the README" % part)
            self.assertIn(part, what, "'## What it does' does not explain '%s'" % part)

    def test_says_how_to_start_it(self):
        run = self.section("How to run")
        for needed in ("python3 dashboard/server.py", "http://localhost:8765", "--root"):
            self.assertIn(needed, run, "'## How to run' should mention %s" % needed)

    def test_says_how_it_is_built(self):
        built = self.section("How it is built")
        for part in ("server.py", "index.html", "fixtures/", "checks/", "tests/", "framework/aaf.py"):
            self.assertIn(part, built, "'## How it is built' should mention %s" % part)
        self.assertIn("Agentic AI Framework", self.text)

    def test_paths_it_names_exist(self):
        # Every file or folder named in backticks must exist: a path in this project or the workspace,
        # a bare file name (`aaf.py`) somewhere in the workspace.
        for ref in named_paths(self.text):
            self.assertTrue(exists(ref), "README.md names %s, which does not exist" % ref)

    def test_path_finder_reads_like_markdown(self):
        # Paths inside a longer command count; code blocks are commands to copy, not references, and must
        # not throw off which backticks pair up; a span that is one file name may contain a space.
        sample = ("Run `python3 framework/gone.py stats <name>`, see `/task`.\n\n```\n.venv/bin/pip install x\n```\n\n"
                  "Then read `old/notes.md` or double-click `Open Dashboard.command`.\n")
        self.assertEqual(named_paths(sample), {"framework/gone.py", "old/notes.md", "Open Dashboard.command"})
        self.assertFalse(exists("framework/gone.py"))
        self.assertTrue(exists("aaf.py") and exists("Open Dashboard.command"))

    def test_generated_sections_are_not_references(self):
        # The generated sections list check commands (.venv/bin/python checks/x.py; ...); like code blocks,
        # they are commands, written by aaf.py, not paths the README points to. Prose around them still counts.
        sample = ("See `old/gone.md`.\n<!-- aaf:checks:start -->\n- **A**: `if [ -x .venv/bin/python ]; then "
                  ".venv/bin/python checks/a.py; fi`\n<!-- aaf:checks:end -->\n")
        self.assertEqual(named_paths(sample), {"old/gone.md"})

    def test_local_only_files_do_not_count(self):
        # Ignored by Git, so missing on a fresh clone: naming them would fail the check there.
        if kept_files(PROJECT) is None:
            self.skipTest("not a Git repository")
        for local in (".venv/bin/pip", "state/activity.jsonl"):
            self.assertFalse(exists(local), "%s is ignored by Git but counted as existing" % local)

    def test_what_it_does_avoids_file_names(self):
        # The first section is for people who have never seen the project: no file or folder names.
        refs = named_paths(self.section("What it does"))
        self.assertEqual(refs, set(), "'## What it does' should say in words what these are: %s" % sorted(refs))

    def test_claude_md_lists_every_test_file(self):
        # The project's CLAUDE.md says what the Server API check runs; every test file must be named there.
        claude = read(os.path.join(PROJECT, "CLAUDE.md"))
        for fn in sorted(os.listdir(os.path.join(PROJECT, "tests"))):
            if fn.startswith("test_") and fn.endswith(".py"):
                self.assertTrue("tests/" + fn in claude, "CLAUDE.md does not say the Server API check runs tests/%s" % fn)


def named_paths(text):
    """Files and folders named in inline backticks, also inside a longer command. Fenced code blocks are
    left out, and so are the sections `aaf.py git commit` generates (they list the check commands). A span that is a single file name is taken whole (it may contain a space); otherwise every
    token with a slash or a file ending. Commands (/task), URLs, options and placeholders are not paths."""
    text = re.sub(r"^```.*?^```[^\n]*$", "", text, flags=re.M | re.S)
    text = re.sub(r"<!-- aaf:(\w+):start -->.*?<!-- aaf:\1:end -->", "", text, flags=re.S)
    ending = r"\.(py|md|html|json|jsonl|command)$"
    refs = set()
    for span in re.findall(r"`([^`\n]+)`", text):
        if re.search(ending, span) and not re.search(r"[<>*=|]|^(python3|cd) ", span):
            refs.add(span)
            continue
        for tok in span.split():
            if "/" not in tok and not re.search(ending, tok):
                continue
            if tok.startswith(("http", "--", "/")) or any(c in tok for c in "<>*=|"):
                continue
            refs.add(tok.rstrip("/"))
    return refs


def kept_files(folder):
    """Files Git keeps or would keep in this repository (tracked, or new and not ignored), as paths relative
    to it; None when the folder is not a Git repository. Local files such as .venv or the live activity log
    are ignored, so they never make a reference look valid on this machine only."""
    if not os.path.isdir(os.path.join(folder, ".git")):
        return None
    out = subprocess.run(["git", "-C", folder, "ls-files", "-co", "--exclude-standard"],
                         capture_output=True, text=True, timeout=30)
    return set(out.stdout.splitlines()) if out.returncode == 0 else None


_KEPT = {}


def exists(ref):
    """A path in this project or the workspace (a folder counts when a kept file lies inside it), or a bare
    file name (`aaf.py`) anywhere in either. Outside a Git repository, the disk is asked instead."""
    for base in (PROJECT, WORKSPACE):
        if base not in _KEPT:
            _KEPT[base] = kept_files(base)
        files = _KEPT[base]
        if files is None:
            if os.path.exists(os.path.join(base, ref)):
                return True
        elif ref in files or any(f.startswith(ref + "/") for f in files) or \
                ("/" not in ref and any(os.path.basename(f) == ref for f in files)):
            return True
    return False

if __name__ == "__main__":
    unittest.main()
