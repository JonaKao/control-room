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
        self.assertEqual(names, {"brand-new", "example-done", "image-classifier", "parser", "scheduler"})

    def test_detail_has_all_sections(self):
        for name in ("brand-new", "example-done", "image-classifier", "parser", "scheduler"):
            d = json.loads(self.get("/api/project?name=" + name)[2])
            for key in ("summary", "meta", "status", "checks", "check_history", "review",
                        "decisions", "progress", "events", "plots", "drafts"):
                self.assertIn(key, d, "%s missing %s" % (name, key))

    def test_waiting_project_exposes_its_draft(self):
        d = json.loads(self.get("/api/project?name=parser")[2])
        self.assertEqual(d["status"]["phase"], "waiting")
        self.assertEqual(len(d["drafts"]), 1)
        self.assertEqual(d["drafts"][0]["id"], "fix-1")

    def test_plots_are_served(self):
        code, ctype, _ = self.get("/plot?project=example-done&file=loss.svg")
        self.assertEqual(code, 200)
        self.assertIn("svg", ctype)

    def test_rejects_path_traversal_and_unknown_projects(self):
        self.assertEqual(self.status_of("/plot?project=example-done&file=../project.json"), 404)
        self.assertEqual(self.status_of("/plot?project=../..&file=loss.svg"), 404)
        self.assertEqual(self.status_of("/api/project?name=nope"), 404)


if __name__ == "__main__":
    unittest.main()
