"""The server's API returns what the page needs, for every fixture state."""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)
import server  # noqa: E402

FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.set_root(FIXTURES)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()

    def status_of(self, path):
        try:
            return self.get(path)[0]
        except urllib.error.HTTPError as e:
            return e.code

    def test_page_is_served(self):
        code, ctype, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"<html", body)

    def test_lists_every_fixture_project(self):
        names = {p["name"] for p in json.loads(self.get("/api/projects")[2])}
        self.assertEqual(names, {"brand-new", "example-done", "image-classifier", "parser", "scheduler", "web-scraper"})

    def test_detail_has_all_sections(self):
        for name in ("brand-new", "example-done", "image-classifier", "parser", "scheduler", "web-scraper"):
            d = json.loads(self.get("/api/project?name=" + name)[2])
            for key in ("summary", "meta", "status", "checks", "check_history", "review",
                        "decisions", "progress", "events", "plots", "drafts", "activity"):
                self.assertIn(key, d, "%s missing %s" % (name, key))

    def test_waiting_project_exposes_its_draft(self):
        d = json.loads(self.get("/api/project?name=parser")[2])
        self.assertEqual(d["status"]["phase"], "waiting")
        self.assertEqual(len(d["drafts"]), 1)
        self.assertEqual(d["drafts"][0]["id"], "fix-1")

    def test_activity_feed(self):
        d = json.loads(self.get("/api/project?name=web-scraper")[2])
        self.assertEqual([a["kind"] for a in d["activity"]][-2:], ["command", "waiting"])
        self.assertEqual(d["summary"]["activity"]["kind"], "waiting")
        empty = json.loads(self.get("/api/project?name=brand-new")[2])
        self.assertEqual(empty["activity"], [])
        self.assertIsNone(empty["summary"]["activity"])
        listed = {p["name"]: p for p in json.loads(self.get("/api/projects")[2])}
        self.assertEqual(listed["web-scraper"]["activity"]["kind"], "waiting")

    def test_plots_are_served(self):
        code, ctype, _ = self.get("/plot?project=example-done&file=loss.svg")
        self.assertEqual(code, 200)
        self.assertIn("svg", ctype)

    def test_rejects_path_traversal_and_unknown_projects(self):
        self.assertEqual(self.status_of("/plot?project=example-done&file=../project.json"), 404)
        self.assertEqual(self.status_of("/plot?project=../..&file=loss.svg"), 404)
        self.assertEqual(self.status_of("/api/project?name=nope"), 404)



class ActivityTailTest(unittest.TestCase):
    """The activity log can grow to about 1 MB; the server reads only its end, every poll."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "activity.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir)

    def test_returns_the_newest_entries_in_order(self):
        with open(self.path, "w") as f:
            for i in range(20000):
                f.write(json.dumps({"ts": "t", "kind": "read", "text": "step %d %s" % (i, "x" * 30)}) + "\n")
        rows = server.read_jsonl_tail(self.path, 30)
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[-1]["text"].split()[1], "19999")
        self.assertEqual(rows[0]["text"].split()[1], "19970")

    def test_reads_only_the_end_of_a_big_file(self):
        with open(self.path, "w") as f:
            f.write("x" * 2_000_000 + "\n")
            f.write(json.dumps({"kind": "edit", "text": "last"}) + "\n")
        read = []
        real_open = open

        class Counting:
            def __init__(self, fh):
                self.fh = fh

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.fh.close()

            def read(self, *a):
                data = self.fh.read(*a)
                read.append(len(data))
                return data

            def __getattr__(self, name):
                return getattr(self.fh, name)
        server.open = lambda *a, **k: Counting(real_open(*a, **k))
        try:
            rows = server.read_jsonl_tail(self.path, 30)
        finally:
            del server.open
        self.assertEqual(rows, [{"kind": "edit", "text": "last"}])
        self.assertLess(sum(read), 300_000, "read %d bytes of a 2 MB log to get its last line" % sum(read))

    def test_skips_broken_lines_and_missing_file(self):
        with open(self.path, "w") as f:
            f.write('{"kind": "read"}\nnot json\n["a list"]\n{"kind": "edit"')
        self.assertEqual(server.read_jsonl_tail(self.path, 30), [{"kind": "read"}])
        self.assertEqual(server.read_jsonl_tail(os.path.join(self.dir, "missing.jsonl"), 30), [])


class TimelineTest(unittest.TestCase):
    """/api/project carries the task timeline: exactly what aaf.py's task_stats derives, cached until
    the event log changes."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.dirname(PROJECT)), "framework", "aaf.py")
        spec = importlib.util.spec_from_file_location("aaf_for_test", path)
        cls.aaf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.aaf)

    def setUp(self):
        import shutil
        import tempfile
        self.old_root = server.ROOT
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(FIXTURES, "projects"), os.path.join(self.tmp, "projects"))
        server.set_root(self.tmp)
        server._stats_cache.clear()

    def tearDown(self):
        import shutil
        server.set_root(self.old_root)
        server._stats_cache.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_as_aaf_stats(self):
        for name in ("brand-new", "example-done", "image-classifier", "parser", "scheduler", "web-scraper"):
            d = server.detail(name)
            self.assertIn("tasks", d, name)
            want = self.aaf.task_stats(os.path.join(self.tmp, "projects", name))
            self.assertEqual(d["tasks"]["tasks"], want["tasks"], name)
            self.assertTrue(d["tasks"]["available"], name)
        self.assertEqual(server.detail("brand-new")["tasks"]["tasks"], [])

    def test_cached_until_the_event_log_changes(self):
        runs = []
        real = server._stats_run
        server._stats_run = lambda pdir: runs.append(pdir) or real(pdir)
        try:
            server.task_stats("parser")
            server.task_stats("parser")
            self.assertEqual(len(runs), 1)
            with open(os.path.join(self.tmp, "projects", "parser", "state", "events.jsonl"), "a") as f:
                f.write(json.dumps({"ts": "2026-10-14T14:00:00+02:00", "kind": "status", "text": "Planning: Next",
                                    "phase": "planning", "iteration": 0, "task": "Next"}) + "\n")
            d = server.task_stats("parser")
            self.assertEqual(len(runs), 2)
            self.assertEqual(d["tasks"][-1]["task"], "Next")
        finally:
            server._stats_run = real

    def test_events_filtered_by_time_not_text(self):
        # 13 tasks; the oldest shown starts 10:00+02:00. An event at 09:30+01:00 (= 10:30+02:00) belongs to it.
        path = os.path.join(self.tmp, "projects", "parser", "state", "events.jsonl")
        with open(path, "w") as f:
            for h in range(13):
                f.write(json.dumps({"ts": "2026-10-14T%02d:00:00+02:00" % (9 + h), "kind": "status", "text": "Planning: T%d" % h,
                                    "phase": "planning", "iteration": 0, "task": "T%d" % h}) + "\n")
                if h == 1:
                    f.write(json.dumps({"ts": "2026-10-14T09:30:00+01:00", "kind": "decision", "text": "Mixed offset"}) + "\n")
        d = server.task_stats("parser")
        self.assertIn("Mixed offset", [e["text"] for e in d["events"]])
        self.assertNotIn("Planning: T0", [e["text"] for e in d["events"]])

    def test_failed_run_is_not_cached(self):
        real = server._stats_run
        calls = []
        def flaky(pdir):
            calls.append(1)
            return {"available": False, "summary": {}, "tasks": [], "error": "boom"} if len(calls) == 1 else real(pdir)
        server._stats_run = flaky
        try:
            self.assertFalse(server.task_stats("parser")["available"])
            self.assertTrue(server.task_stats("parser")["available"])
        finally:
            server._stats_run = real

    def test_unavailable_without_aaf(self):
        real = server.stats_aaf_path
        server.stats_aaf_path = lambda: None
        try:
            d = server.task_stats("parser")
        finally:
            server.stats_aaf_path = real
        self.assertFalse(d["available"])
        self.assertEqual(d["tasks"], [])


if __name__ == "__main__":
    unittest.main()
