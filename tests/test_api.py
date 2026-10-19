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
        self.assertEqual(names, {"api-client", "brand-new", "data-pipeline", "example-done", "image-classifier", "notes-app", "parser", "scheduler",
                   "web-scraper"})

    def test_detail_has_all_sections(self):
        for name in ("api-client", "brand-new", "data-pipeline", "example-done", "image-classifier", "notes-app", "parser", "scheduler",
                   "web-scraper"):
            d = json.loads(self.get("/api/project?name=" + name)[2])
            for key in ("summary", "meta", "status", "checks", "check_history", "review",
                        "decisions", "progress", "events", "plots", "drafts", "activity", "record", "estimate"):
                self.assertIn(key, d, "%s missing %s" % (name, key))

    def test_workspace_record_endpoint(self):
        code, ctype, body = self.get("/api/record")
        self.assertEqual(code, 200)
        w = json.loads(body)
        self.assertEqual(len(w["projects"]), 9)
        self.assertEqual(w["reasons"][0]["key"], "progress")

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
        self.assertNotIn("resolved", listed["web-scraper"]["activity"])
        # notes-app: the reviewer's command needed permission, which was granted (a quiet "done" followed).
        notes = json.loads(self.get("/api/project?name=notes-app")[2])
        self.assertFalse(any(a.get("quiet") for a in notes["activity"]))
        self.assertEqual(notes["activity"][-1]["kind"], "waiting")
        self.assertEqual(notes["activity"][-1]["resolved"], "done")
        self.assertEqual(listed["notes-app"]["activity"]["resolved"], "done")
        self.assertIn("error", [a["kind"] for a in notes["activity"]])
        self.assertIn("you", [a["kind"] for a in notes["activity"]])

    def test_project_list_carries_trend_and_plan(self):
        listed = {p["name"]: p for p in json.loads(self.get("/api/projects")[2])}
        # Share of tests passing per run, oldest first, at most 12 runs.
        sched = listed["scheduler"]["trend"]
        self.assertTrue(0 < len(sched) <= 12)
        self.assertTrue(all(0 <= x <= 1 for x in sched))
        self.assertEqual(listed["brand-new"]["trend"], [])
        self.assertEqual(listed["image-classifier"]["plan"]["total"], 5)
        self.assertEqual(listed["image-classifier"]["plan"]["done"], 2)
        self.assertTrue(listed["image-classifier"]["plan"]["current"])
        self.assertIsNone(listed["brand-new"]["plan"])

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


class ActivityStepsTest(unittest.TestCase):
    """The hook also writes quiet "done" records, "error" and "you" records and a tool_use_id per step
    (framework update 2026-10-19). Quiet records are not steps; they and "you" resolve a wait."""

    def steps(self, rows):
        return server.activity_steps(rows)

    def test_quiet_records_are_not_steps(self):
        rows = [{"ts": "1", "kind": "read", "text": "Reading a", "tool_use_id": "t1"},
                {"ts": "2", "kind": "done", "text": "Finished: reading a", "tool_use_id": "t1", "quiet": True},
                {"ts": "3", "kind": "edit", "text": "Editing a", "tool_use_id": "t2"}]
        self.assertEqual([r["kind"] for r in self.steps(rows)], ["read", "edit"])

    def test_done_for_the_same_step_resolves_a_permission_wait(self):
        rows = [{"ts": "1", "kind": "command", "text": "Run it", "tool_use_id": "t1"},
                {"ts": "2", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
                {"ts": "3", "kind": "waiting", "text": "Waiting for your permission in Claude Code"},
                {"ts": "4", "kind": "done", "text": "Finished: run it", "tool_use_id": "t1", "quiet": True}]
        out = self.steps(rows)
        # The notification without an id is the same prompt, not a second wait.
        self.assertEqual([r["kind"] for r in out], ["command", "waiting"])
        self.assertEqual(out[-1]["tool_use_id"], "t1")
        self.assertEqual(out[-1]["resolved"], "done")
        self.assertEqual(out[-1]["resolved_ts"], "4")

    def test_a_wait_without_an_id_is_resolved_with_the_waits_before_it(self):
        rows = [{"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
                {"ts": "2", "kind": "waiting", "text": "Waiting for your reply in Claude Code"},
                {"ts": "3", "kind": "done", "text": "Finished", "tool_use_id": "t1", "quiet": True}]
        self.assertEqual([r.get("resolved") for r in self.steps(rows)], ["done", "done"])

    def test_done_for_another_step_does_not_resolve_it(self):
        rows = [{"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
                {"ts": "2", "kind": "done", "text": "Finished: other", "tool_use_id": "t9", "quiet": True}]
        self.assertNotIn("resolved", self.steps(rows)[-1])

    def test_error_reply_and_next_step_resolve_waits(self):
        rows = [{"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
                {"ts": "2", "kind": "error", "text": "A step did not work: run it", "tool_use_id": "t1", "detail": "exit 1"},
                {"ts": "3", "kind": "waiting", "text": "Waiting for your reply in Claude Code"},
                {"ts": "4", "kind": "you", "text": "You sent a message in Claude Code"},
                {"ts": "5", "kind": "waiting", "text": "Waiting for your reply in Claude Code"},
                {"ts": "6", "kind": "read", "text": "Reading b"}]
        out = self.steps(rows)
        self.assertEqual([r["kind"] for r in out], ["waiting", "error", "waiting", "you", "waiting", "read"])
        self.assertEqual([out[i].get("resolved") for i in (0, 2, 4)], ["error", "you", "step"])
        self.assertEqual(out[1]["detail"], "exit 1")

    def test_the_duplicate_prompt_counts_once_in_either_order(self):
        rows = [{"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code"},
                {"ts": "2", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"}]
        out = self.steps(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["tool_use_id"], "t1")

    def test_notes_turns_and_other_agents_are_no_answer(self):
        for later in ({"ts": "2", "kind": "turn", "text": "Finished its turn"},
                      {"ts": "2", "kind": "note", "text": "Notification"},
                      {"ts": "2", "kind": "read", "text": "Reading b", "subagent": "reviewer"}):
            rows = [{"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"}, later]
            self.assertNotIn("resolved", self.steps(rows)[0], later)
        rows = [{"ts": "1", "kind": "waiting", "text": "Waiting for your reply in Claude Code", "subagent": "reviewer"},
                {"ts": "2", "kind": "read", "text": "Reading b", "subagent": "reviewer"}]
        self.assertEqual(self.steps(rows)[0]["resolved"], "step")

    def test_feed_keeps_thirty_steps_however_many_quiet_records(self):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, "activity.jsonl")
        with open(path, "w") as f:
            for i in range(100):
                f.write(json.dumps({"ts": str(i), "kind": "read", "text": "step %d" % i, "tool_use_id": "t%d" % i}) + "\n")
                f.write(json.dumps({"ts": str(i), "kind": "done", "text": "done", "tool_use_id": "t%d" % i, "quiet": True}) + "\n")
        try:
            rows = server.read_activity(path, server.ACTIVITY_LAST)
        finally:
            import shutil
            shutil.rmtree(d)
        self.assertEqual(len(rows), server.ACTIVITY_LAST)
        self.assertEqual(rows[-1]["text"], "step 99")
        self.assertFalse(any(r.get("quiet") for r in rows))


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
        for name in ("api-client", "brand-new", "data-pipeline", "example-done", "image-classifier", "notes-app", "parser", "scheduler",
                   "web-scraper"):
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


class TrackRecordTest(unittest.TestCase):
    """Why reviews said no, grouped by theme; /api/project carries it per project, /api/record for all."""

    def setUp(self):
        self.old_root = server.ROOT
        server.set_root(FIXTURES)

    def tearDown(self):
        server.set_root(self.old_root)

    def test_groups_failed_reviews_most_common_first_other_last(self):
        rows = [{"at": "1", "verdict": "fail", "summary": "Strange edge in the parser"},
                {"at": "2", "verdict": "fail", "summary": "progress.md not updated"},
                {"at": "3", "verdict": "pass", "summary": "progress.md not updated"},
                {"at": "4", "verdict": "FAIL", "summary": "Bug: crash on empty input; progress note stale"},
                {"at": "5", "verdict": "fail", "summary": ""}]
        got = [(g["key"], g["count"]) for g in server.review_reasons(rows)]
        self.assertEqual(got, [("progress", 2), ("bug", 1), ("other", 2)])
        progress = server.review_reasons(rows)[0]
        self.assertEqual([e["at"] for e in progress["examples"]], ["4", "2"])  # newest first

    def test_matches_the_definition_of_done(self):
        items = ["Every check passes", "`state/progress.md` says what changed"]
        groups = {g["key"]: g for g in server.review_reasons(
            [{"verdict": "fail", "summary": "progress note missing"}, {"verdict": "fail", "summary": "a race"}], items)}
        self.assertEqual(groups["progress"]["done_item"], "`state/progress.md` says what changed")
        self.assertIsNone(groups["bug"]["done_item"])
        self.assertTrue(groups["bug"]["advice"])
        self.assertIn("state/progress.md says what changed and what is next", server.done_items("api-client"))

    def test_project_record(self):
        rec = server.detail("api-client")["record"]
        self.assertEqual(len(rec["reviews"]), 15)
        self.assertEqual([(g["key"], g["count"]) for g in rec["reasons"]],
                         [("progress", 3), ("weakened", 1), ("coverage", 1), ("bug", 1)])
        self.assertEqual(server.record("brand-new"), {"reviews": [], "reasons": []})

    def test_workspace_record(self):
        w = server.workspace_record()
        self.assertTrue(w["available"])
        self.assertEqual([p["name"] for p in w["projects"]], server.project_names())
        api = [p for p in w["projects"] if p["name"] == "api-client"][0]
        self.assertEqual(api["summary"]["review_fails"], 6)
        self.assertEqual(len(api["tasks"]), 9)
        self.assertEqual(set(api["tasks"][0]), set(server.TASK_KEYS))
        self.assertEqual([(g["key"], g["projects"]) for g in w["reasons"]][-1], ("other", ["parser"]))

    def test_workspace_reasons_know_each_definition_of_done(self):
        groups = {g["key"]: g for g in server.workspace_record()["reasons"]}
        # api-client's DONE.md has an item for the progress note; nothing covers a bug.
        self.assertEqual(groups["progress"]["covered_in"], ["api-client"])
        self.assertEqual(groups["bug"]["covered_in"], [])

    def test_overlapping_themes_are_counted_per_rejection(self):
        rows = [{"verdict": "fail", "summary": "progress note missing and a crash"}, {"verdict": "fail", "summary": "a race"}]
        self.assertEqual(server.review_reasons(rows)[0]["rejections"], 2)



class EstimateTest(unittest.TestCase):
    """/api/project carries the time estimate: exactly what aaf.py's estimate() gives for the served
    workspace at the server's clock, plus aaf's calibration (how often past ranges held), cached briefly."""
    NOW = "2026-10-14T14:50:00+02:00"

    @classmethod
    def setUpClass(cls):
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.dirname(PROJECT)), "framework", "aaf.py")
        spec = importlib.util.spec_from_file_location("aaf_for_estimate", path)
        cls.aaf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.aaf)

    def setUp(self):
        import shutil
        import tempfile
        self.old_root, self.old_clock = server.ROOT, server.CLOCK
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(FIXTURES, "projects"), os.path.join(self.tmp, "projects"))
        server.set_root(self.tmp)
        server.CLOCK = self.NOW
        server._estimate_cache.clear()

    def tearDown(self):
        import shutil
        server.set_root(self.old_root)
        server.CLOCK = self.old_clock
        server._estimate_cache.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def expected(self, root, name):
        """aaf.estimate() on <root>/projects/<name> with the clock at NOW (written here, not taken from server.py)."""
        import datetime as real
        import types
        now = real.datetime.fromisoformat(self.NOW)

        class Fixed(real.datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz is None else now.astimezone(tz)
        old_projects, old_dt = self.aaf.PROJECTS, self.aaf.dt
        self.aaf.PROJECTS = os.path.join(root, "projects")
        self.aaf.dt = types.SimpleNamespace(datetime=Fixed, timedelta=real.timedelta, timezone=real.timezone,
                                            date=real.date)
        try:
            return self.aaf.estimate(os.path.join(root, "projects", name)), self.aaf._calibration()
        finally:
            self.aaf.PROJECTS, self.aaf.dt = old_projects, old_dt

    def test_same_as_aaf_estimate(self):
        active = 0
        for name in sorted(os.listdir(os.path.join(self.tmp, "projects"))):
            got = server.detail(name)["estimate"]
            want, cal = self.expected(self.tmp, name)
            self.assertTrue(got.pop("available"), name)
            self.assertEqual(got.pop("held"), cal, name)
            self.assertEqual(got, want, name)
            active += want["active"]
        self.assertEqual(active, 4)  # data-pipeline, image-classifier, notes-app, web-scraper

    def test_scenarios(self):
        e = server.detail("image-classifier")["estimate"]
        self.assertEqual(e["plan"], {"steps": 5, "done": 2, "current": "Retrain and compare validation accuracy"})
        self.assertLess(e["progress_low"], e["progress_high"])
        self.assertIn("past review and fixing", server.detail("notes-app")["estimate"]["basis"])
        self.assertIn("longer than almost every", server.detail("data-pipeline")["estimate"]["basis"])
        longest = max(t["duration_s"] or 0 for n in os.listdir(os.path.join(self.tmp, "projects"))
                      for t in self.aaf.task_stats(os.path.join(self.tmp, "projects", n))["tasks"] if t["outcome"] != "running")
        self.assertGreater(server.detail("data-pipeline")["estimate"]["elapsed_s"], longest,
                           "data-pipeline runs longer than any task before it")
        held = server.detail("brand-new")["estimate"]["held"]
        self.assertEqual((held["predictions_checked"], held["coverage"]), (10, 0.7))

    def test_no_history(self):
        root = os.path.join(PROJECT, "fixtures", "first-run")
        server.set_root(root)
        got = server.detail("first-project")["estimate"]
        want, cal = self.expected(root, "first-project")
        self.assertEqual(got["remaining_low_s"], None)
        self.assertEqual(got["basis"], "too little history")
        self.assertEqual(got["held"]["predictions_checked"], 0)
        got.pop("available"), got.pop("held")
        self.assertEqual(got, want)

    def test_cached_briefly(self):
        first = server.detail("notes-app")["estimate"]
        path = os.path.join(self.tmp, "projects", "notes-app", "state", "status.json")
        with open(path) as f:
            st = json.load(f)
        st["phase"] = "done"
        with open(path, "w") as f:
            json.dump(st, f)
        self.assertEqual(server.detail("notes-app")["estimate"], first, "asked again at once: from the cache")
        key = (server.ROOT, "notes-app")
        server._estimate_cache[key] = (server._estimate_cache[key][0] - server.ESTIMATE_CACHE_S - 1,
                                       server._estimate_cache[key][1])
        self.assertEqual(server.detail("notes-app")["estimate"]["active"], False, "after the cache time: fresh")

    def test_failed_run_is_not_repeated_on_every_poll(self):
        calls = []
        real = server.subprocess.run

        def failing(*a, **k):
            calls.append(1)
            return real([sys.executable, "-c", "import sys; sys.exit(1)"], capture_output=True, text=True)
        server.subprocess.run = failing
        try:
            first = server.estimate("notes-app")
            second = server.estimate("notes-app")
        finally:
            server.subprocess.run = real
        self.assertFalse(first["available"])
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 1, "a failed estimate is kept briefly, not retried on every request")

    def test_unavailable_without_aaf(self):
        old = server.stats_aaf_path
        server.stats_aaf_path = lambda: None
        try:
            self.assertEqual(server.detail("notes-app")["estimate"], {"available": False})
        finally:
            server.stats_aaf_path = old


if __name__ == "__main__":
    unittest.main()
