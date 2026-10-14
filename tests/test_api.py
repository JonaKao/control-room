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


if __name__ == "__main__":
    unittest.main()
