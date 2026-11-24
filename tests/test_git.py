"""Git endpoints of the Rust core (`control-room serve`): data comes from `aaf.py git info`, push/pull
go through `aaf.py git push|pull`, and only the page itself (localhost, custom header) may ask for a
push or pull.

Tests run against temporary workspaces with real repositories (checks/git_workspace.py):
one shared by the read-only tests, a fresh one for each test that pushes, pulls or changes
a phase. Nothing Git-related is stored in the fixtures. What needs the core's insides (requests
sharing one fetch, counting aaf.py runs) is a Rust unit test; the tests naming one check that it
passed in this run of `cargo test` (checks/app_server.py rust_test).
"""
import http.client
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "checks"))
import app_server  # noqa: E402
import git_workspace as gw  # noqa: E402

HEADER = {"X-AAF-Request": "control-room", "Content-Type": "application/json"}
FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")


class GitServer:
    """Serves a temporary workspace with real repositories (see checks/git_workspace.py)."""

    @classmethod
    def start_workspace(cls):
        cls.root, cls.expect = gw.make_workspace()
        cls.srv = app_server.Served(cls.root)
        cls.port = cls.srv.port

    @classmethod
    def stop_workspace(cls):
        cls.srv.stop()
        gw.remove_workspace(cls.root)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        r = conn.getresponse()
        data = r.read()
        conn.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data.decode(errors="replace")

    def info(self, name):
        code, d = self.request("GET", "/api/git?name=%s&fresh=1" % name)
        self.assertEqual(code, 200, d)
        return d

    def set_phase(self, name, phase):
        path = os.path.join(self.root, "projects", name, "state", "status.json")
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        st["phase"] = phase
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f)

    def remote_log(self, name):
        return gw.git(os.path.join(self.root, "remotes", name + ".git"), "log", "--format=%s", "main")


class GitApiTest(GitServer, unittest.TestCase):
    """Reading and request checks. None of these change the workspace, so they share one."""

    @classmethod
    def setUpClass(cls):
        cls.start_workspace()

    @classmethod
    def tearDownClass(cls):
        cls.stop_workspace()


    # --- reading

    def test_info_reports_commits_trailers_and_sync_state(self):
        d = self.info("example-done")
        self.assertTrue(d["repo"])
        self.assertEqual(len(d["commits"]), self.expect["example-done"]["commits"])
        self.assertEqual(d["ahead"], 2)
        self.assertEqual(d["behind"], 0)
        newest = d["commits"][0]
        self.assertEqual(newest["subject"], "Tidy up after review")
        self.assertEqual(newest["trailers"].get("Checks"), "2/2")
        self.assertEqual(newest["trailers"].get("Review"), "pass")
        self.assertIn("hand-written lexer", d["commits"][3]["body"])

    def test_info_reports_behind_and_uncommitted_files(self):
        d = self.info("parser")
        self.assertEqual(d["behind"], 1)
        self.assertEqual(d["n_changed"], 1)
        self.assertIn("notes.txt", d["changed"])

    def test_info_for_project_without_git(self):
        d = self.info("brand-new")
        self.assertFalse(d["repo"])

    def test_info_rejects_unknown_and_traversal(self):
        for name in ("nope", "..", "../..", "example-done/../parser"):
            code, _ = self.request("GET", "/api/git?name=" + name)
            self.assertEqual(code, 404, name)

    # --- who may write

    def test_write_needs_the_page_header(self):
        before = self.remote_log("example-done")
        code, _ = self.request("POST", "/api/git/push", {"name": "example-done"},
                               {"Content-Type": "application/json"})
        self.assertEqual(code, 403)
        self.assertEqual(self.remote_log("example-done"), before)

    def test_write_rejects_foreign_origin_and_host(self):
        before = self.remote_log("example-done")
        for extra in ({"Origin": "https://evil.example"}, {"Host": "evil.example"},
                      {"Origin": "http://localhost:1"}):
            code, _ = self.request("POST", "/api/git/push", {"name": "example-done"}, dict(HEADER, **extra))
            self.assertEqual(code, 403, extra)
        self.assertEqual(self.remote_log("example-done"), before)

    def test_write_is_post_only_and_known_actions_only(self):
        code, _ = self.request("GET", "/api/git/push?name=example-done")
        self.assertIn(code, (404, 405))
        code, _ = self.request("POST", "/api/git/reset", {"name": "example-done"}, HEADER)
        self.assertEqual(code, 404)
        code, _ = self.request("POST", "/api/git/push", {"name": "../.."}, HEADER)
        self.assertEqual(code, 404)
        code, _ = self.request("OPTIONS", "/api/git/push")
        self.assertNotEqual(code, 204)

    def test_bad_content_length_is_refused_quickly(self):
        import socket
        for length in ("-1", "abc", "99999"):
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            sock.sendall(("POST /api/git/push HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n"
                          "X-AAF-Request: control-room\r\nContent-Type: application/json\r\n"
                          "Content-Length: %s\r\n\r\n" % (self.port, length)).encode())
            try:
                status = sock.recv(64).decode(errors="replace")
            except socket.timeout:
                status = "timed out"
            finally:
                sock.close()
            self.assertTrue(status.startswith("HTTP/1.0 4") or status.startswith("HTTP/1.1 4"),
                            "Content-Length %s: %r" % (length, status))

class GitWriteTest(GitServer, unittest.TestCase):
    """Push, pull and phase changes alter the repositories, so each test gets its own workspace."""

    def setUp(self):
        self.start_workspace()

    def tearDown(self):
        self.stop_workspace()

    def test_push_sends_local_commits(self):
        code, d = self.request("POST", "/api/git/push", {"name": "example-done"},
                               dict(HEADER, Origin="http://127.0.0.1:%d" % self.port))
        self.assertEqual(code, 200, d)
        self.assertTrue(d["ok"])
        self.assertIn("Tidy up after review", self.remote_log("example-done"))
        self.assertEqual(self.info("example-done")["ahead"], 0)

    def test_pull_refused_while_agent_works(self):
        self.set_phase("image-classifier", "checking")
        code, d = self.request("POST", "/api/git/pull", {"name": "image-classifier"}, HEADER)
        self.assertEqual(code, 409, d)
        self.assertFalse(d["ok"])
        self.assertEqual(self.info("image-classifier")["behind"], 1)

    def test_pull_brings_newer_commits_when_idle(self):
        self.set_phase("parser", "waiting")
        code, d = self.request("POST", "/api/git/pull", {"name": "parser"}, HEADER)
        self.assertEqual(code, 200, d)
        self.assertTrue(d["ok"])
        self.assertEqual(self.info("parser")["behind"], 0)


class GitTestOrderTest(unittest.TestCase):
    """The Git API tests pass in any order: a push or pull in one test must not change what another sees."""

    def test_api_tests_pass_in_reverse_order(self):
        loader = unittest.TestLoader()
        loader.sortTestMethodsUsing = lambda a, b: (a < b) - (a > b)
        suite = unittest.TestSuite(loader.loadTestsFromTestCase(c) for c in (GitWriteTest, GitApiTest))
        with open(os.devnull, "w", encoding="utf-8") as quiet:
            result = unittest.TextTestRunner(stream=quiet, verbosity=0).run(suite)
        failed = [str(t) for t, _ in result.failures + result.errors]
        self.assertTrue(result.wasSuccessful(), "fail when run in reverse order: %s" % failed)


class GitInfoSingleFlightTest(unittest.TestCase):
    """When the cache runs out, simultaneous requests share one `aaf.py git info --fetch` (aaf.rs)."""

    def assertRustPassed(self, name):
        ok, detail = app_server.rust_test(name)
        self.assertTrue(ok, "Rust unit test %s: %s" % (name, detail))

    def test_concurrent_requests_run_aaf_once(self):
        self.assertRustPassed("aaf::tests::concurrent_git_info_requests_run_aaf_once")

    def test_fetch_slower_than_cache_life_still_runs_once(self):
        self.assertRustPassed("aaf::tests::fetch_slower_than_cache_life_still_runs_once")

    def test_fresh_request_does_not_reuse_a_run_that_started_before_it(self):
        self.assertRustPassed("aaf::tests::fresh_request_does_not_reuse_a_run_that_started_before_it")

    def test_fresh_request_reuses_a_run_that_started_after_it(self):
        self.assertRustPassed("aaf::tests::fresh_request_reuses_a_run_that_started_after_it")


class GitWithoutFrameworkTest(unittest.TestCase):
    """A workspace without framework/aaf.py (like the plain fixtures) has no Git data."""

    def test_unavailable(self):
        srv = app_server.Served(FIXTURES)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=60)
            conn.request("GET", "/api/git?name=example-done")
            d = json.loads(conn.getresponse().read())
            conn.close()
        finally:
            srv.stop()
        self.assertFalse(d.get("available", True))


class NoDirectGitTest(unittest.TestCase):
    def test_core_never_runs_git_itself(self):
        src_dir = os.path.join(PROJECT, "app", "src")
        files = [os.path.join(src_dir, f) for f in os.listdir(src_dir) if f.endswith(".rs")]
        self.assertTrue(files)
        for path in files:
            with open(path, encoding="utf-8") as f:
                src = f.read()
            self.assertIsNone(re.search(r'Command::new\(\s*"git(\.exe)?"\s*\)', src),
                              "%s must go through aaf.py, not git" % os.path.basename(path))
        with open(os.path.join(src_dir, "aaf.rs"), encoding="utf-8") as f:
            self.assertIn("aaf.py", f.read())


class ChangeMapApiTest(GitServer, unittest.TestCase):
    """/api/files: the change map's data, exactly `aaf.py git files <name>`, cached like Git info."""

    @classmethod
    def setUpClass(cls):
        cls.start_workspace()
        cls.want = gw.code_repo(cls.root, "scheduler")

    @classmethod
    def tearDownClass(cls):
        cls.stop_workspace()

    def test_same_as_aaf_git_files(self):
        import subprocess
        out = subprocess.run([sys.executable, os.path.join(self.root, "framework", "aaf.py"), "git", "files", "scheduler"],
                             capture_output=True, text=True, check=True, encoding="utf-8", errors="replace").stdout
        code, d = self.request("GET", "/api/files?name=scheduler&fresh=1")
        self.assertEqual(code, 200)
        self.assertTrue(d["available"])
        self.assertTrue(d["repo"])
        self.assertEqual(d["files"], json.loads(out)["files"])
        core = [f for f in d["files"] if f["path"] == "scheduler/core.py"][0]
        self.assertEqual(core["commits"], self.want["scheduler/core.py"][0])

    def test_not_a_repository(self):
        code, d = self.request("GET", "/api/files?name=brand-new")
        self.assertEqual(code, 200)
        self.assertTrue(d["available"])
        self.assertFalse(d["repo"])
        self.assertEqual(d["files"], [])

    def test_unknown_project_and_traversal(self):
        for name in ("nope", "../scheduler", "..%2Fscheduler"):
            code, _ = self.request("GET", "/api/files?name=" + name)
            self.assertEqual(code, 404, name)

    def test_cached_unless_fresh(self):
        ok, detail = app_server.rust_test("aaf::tests::files_cached_unless_fresh_and_failures_not_cached")
        self.assertTrue(ok, detail)
        paths = lambda d: [f["path"] for f in d["files"]]
        _, first = self.request("GET", "/api/files?name=scheduler&fresh=1")
        gw.commit(os.path.join(self.root, "projects", "scheduler"), "Add a new module", touch="scheduler/extra.py")
        _, again = self.request("GET", "/api/files?name=scheduler")
        self.assertEqual(paths(again), paths(first), "asked again at once: from the cache")
        self.assertNotIn("scheduler/extra.py", paths(again))
        _, fresh = self.request("GET", "/api/files?name=scheduler&fresh=1")
        self.assertIn("scheduler/extra.py", paths(fresh), "a fresh request runs aaf.py git files again")

    def test_unavailable_without_framework(self):
        srv = app_server.Served(FIXTURES)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=60)
            conn.request("GET", "/api/files?name=example-done")
            d = json.loads(conn.getresponse().read())
            conn.close()
        finally:
            srv.stop()
        self.assertFalse(d["available"])
        self.assertEqual(d["files"], [])


if __name__ == "__main__":
    unittest.main()
