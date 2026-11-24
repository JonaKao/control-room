"""The Rust core's API (`control-room serve`) returns what the page needs, for every fixture state.

Tests that need the core's insides (reading only the end of a log, the feed's wait rules, the
caches, the review themes) are Rust unit tests now; each test below that names one checks that it
passed in this run of `cargo test` (checks/app_server.py rust_test)."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "checks"))
import app_server  # noqa: E402

FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
NAMES = ("api-client", "brand-new", "data-pipeline", "example-done", "image-classifier", "notes-app", "parser",
         "scheduler", "web-scraper")
TASK_KEYS = ("task", "start", "end", "outcome", "attempts", "first_try", "reviews", "drafts", "times_stuck")
ACTIVITY_LAST = 30


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def get_json(base, path):
    return json.loads(get(base, path)[2])


def load_aaf(name):
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(PROJECT)), "framework", "aaf.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RustTest:
    def assertRustPassed(self, name):
        ok, detail = app_server.rust_test(name)
        self.assertTrue(ok, "Rust unit test %s: %s" % (name, detail))


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = app_server.Served(FIXTURES)
        cls.base = cls.srv.base

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def get(self, path):
        return get(self.base, path)

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
        self.assertEqual(names, set(NAMES))

    def test_detail_has_all_sections(self):
        for name in NAMES:
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


class ActivityTailTest(RustTest, unittest.TestCase):
    """The activity log can grow to about 1 MB; the core reads only its end, every poll (records.rs)."""

    def test_returns_the_newest_entries_in_order(self):
        self.assertRustPassed("records::tests::tail_returns_the_newest_entries_in_order")

    def test_reads_only_the_end_of_a_big_file(self):
        self.assertRustPassed("records::tests::tail_reads_only_the_end_of_a_big_file")

    def test_skips_broken_lines_and_missing_file(self):
        self.assertRustPassed("records::tests::tail_skips_broken_lines_and_missing_file")


class ActivityStepsTest(RustTest, unittest.TestCase):
    """The hook also writes quiet "done" records, "error" and "you" records and a tool_use_id per step
    (framework update 2026-10-19). Quiet records are not steps; they and "you" resolve a wait (activity.rs)."""

    def test_quiet_records_are_not_steps(self):
        self.assertRustPassed("activity::tests::quiet_records_are_not_steps")

    def test_done_for_the_same_step_resolves_a_permission_wait(self):
        self.assertRustPassed("activity::tests::done_for_the_same_step_resolves_a_permission_wait")

    def test_a_wait_without_an_id_is_resolved_with_the_waits_before_it(self):
        self.assertRustPassed("activity::tests::a_wait_without_an_id_is_resolved_with_the_waits_before_it")

    def test_done_for_another_step_does_not_resolve_it(self):
        self.assertRustPassed("activity::tests::done_for_another_step_does_not_resolve_it")

    def test_error_reply_and_next_step_resolve_waits(self):
        self.assertRustPassed("activity::tests::error_reply_and_next_step_resolve_waits")

    def test_the_duplicate_prompt_counts_once_in_either_order(self):
        self.assertRustPassed("activity::tests::the_duplicate_prompt_counts_once_in_either_order")

    def test_notes_turns_and_other_agents_are_no_answer(self):
        self.assertRustPassed("activity::tests::notes_turns_and_other_agents_are_no_answer")

    def test_feed_keeps_thirty_steps_however_many_quiet_records(self):
        self.assertRustPassed("records::tests::feed_keeps_thirty_steps_however_many_quiet_records")
        # And through the API: a long log with quiet records still gives thirty steps.
        tmp = tempfile.mkdtemp()
        try:
            shutil.copytree(os.path.join(FIXTURES, "projects", "brand-new"), os.path.join(tmp, "projects", "brand-new"))
            with open(os.path.join(tmp, "projects", "brand-new", "state", "activity.jsonl"), "w", encoding="utf-8") as f:
                for i in range(100):
                    f.write(json.dumps({"ts": str(i), "kind": "read", "text": "step %d" % i, "tool_use_id": "t%d" % i}) + "\n")
                    f.write(json.dumps({"ts": str(i), "kind": "done", "text": "done", "tool_use_id": "t%d" % i, "quiet": True}) + "\n")
            with app_server.serve(tmp) as base:
                rows = get_json(base, "/api/project?name=brand-new")["activity"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(len(rows), ACTIVITY_LAST)
        self.assertEqual(rows[-1]["text"], "step 99")
        self.assertFalse(any(r.get("quiet") for r in rows))


class TimelineTest(RustTest, unittest.TestCase):
    """/api/project carries the task timeline: exactly what aaf.py's task_stats derives, cached until
    the event log changes."""

    @classmethod
    def setUpClass(cls):
        cls.aaf = load_aaf("aaf_for_test")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(FIXTURES, "projects"), os.path.join(self.tmp, "projects"))
        self.srv = app_server.Served(self.tmp)

    def tearDown(self):
        self.srv.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def detail(self, name):
        return get_json(self.srv.base, "/api/project?name=" + name)

    def test_same_as_aaf_stats(self):
        for name in NAMES:
            d = self.detail(name)
            self.assertIn("tasks", d, name)
            want = self.aaf.task_stats(os.path.join(self.tmp, "projects", name))
            self.assertEqual(d["tasks"]["tasks"], want["tasks"], name)
            self.assertTrue(d["tasks"]["available"], name)
        self.assertEqual(self.detail("brand-new")["tasks"]["tasks"], [])

    def test_cached_until_the_event_log_changes(self):
        self.assertRustPassed("aaf::tests::stats_cached_until_the_event_log_changes_and_failures_retried")
        self.detail("parser")
        with open(os.path.join(self.tmp, "projects", "parser", "state", "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-10-14T14:00:00+02:00", "kind": "status", "text": "Planning: Next",
                                "phase": "planning", "iteration": 0, "task": "Next"}) + "\n")
        self.assertEqual(self.detail("parser")["tasks"]["tasks"][-1]["task"], "Next")

    def test_events_filtered_by_time_not_text(self):
        # 13 tasks; the oldest shown starts 10:00+02:00. An event at 09:30+01:00 (= 10:30+02:00) belongs to it.
        path = os.path.join(self.tmp, "projects", "parser", "state", "events.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for h in range(13):
                f.write(json.dumps({"ts": "2026-10-14T%02d:00:00+02:00" % (9 + h), "kind": "status", "text": "Planning: T%d" % h,
                                    "phase": "planning", "iteration": 0, "task": "T%d" % h}) + "\n")
                if h == 1:
                    f.write(json.dumps({"ts": "2026-10-14T09:30:00+01:00", "kind": "decision", "text": "Mixed offset"}) + "\n")
        d = self.detail("parser")["tasks"]
        self.assertIn("Mixed offset", [e["text"] for e in d["events"]])
        self.assertNotIn("Planning: T0", [e["text"] for e in d["events"]])

    def test_failed_run_is_not_cached(self):
        self.assertRustPassed("aaf::tests::stats_cached_until_the_event_log_changes_and_failures_retried")

    def test_unavailable_without_aaf(self):
        self.assertRustPassed("aaf::tests::unavailable_without_aaf")


class TrackRecordTest(RustTest, unittest.TestCase):
    """Why reviews said no, grouped by theme; /api/project carries it per project, /api/record for all."""

    @classmethod
    def setUpClass(cls):
        cls.srv = app_server.Served(FIXTURES)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_groups_failed_reviews_most_common_first_other_last(self):
        self.assertRustPassed("reasons::tests::groups_failed_reviews_most_common_first_other_last")

    def test_matches_the_definition_of_done(self):
        self.assertRustPassed("reasons::tests::matches_the_definition_of_done")
        groups = {g["key"]: g for g in get_json(self.srv.base, "/api/project?name=api-client")["record"]["reasons"]}
        self.assertEqual(groups["progress"]["done_item"], "state/progress.md says what changed and what is next")

    def test_project_record(self):
        rec = get_json(self.srv.base, "/api/project?name=api-client")["record"]
        self.assertEqual(len(rec["reviews"]), 15)
        self.assertEqual([(g["key"], g["count"]) for g in rec["reasons"]],
                         [("progress", 3), ("weakened", 1), ("coverage", 1), ("bug", 1)])
        self.assertEqual(get_json(self.srv.base, "/api/project?name=brand-new")["record"], {"reviews": [], "reasons": []})

    def test_workspace_record(self):
        w = get_json(self.srv.base, "/api/record")
        self.assertTrue(w["available"])
        self.assertEqual([p["name"] for p in w["projects"]], [p["name"] for p in get_json(self.srv.base, "/api/projects")])
        api = [p for p in w["projects"] if p["name"] == "api-client"][0]
        self.assertEqual(api["summary"]["review_fails"], 6)
        self.assertEqual(len(api["tasks"]), 9)
        self.assertEqual(set(api["tasks"][0]), set(TASK_KEYS))
        self.assertEqual([(g["key"], g["projects"]) for g in w["reasons"]][-1], ("other", ["parser"]))

    def test_workspace_reasons_know_each_definition_of_done(self):
        groups = {g["key"]: g for g in get_json(self.srv.base, "/api/record")["reasons"]}
        # api-client's DONE.md has an item for the progress note; nothing covers a bug.
        self.assertEqual(groups["progress"]["covered_in"], ["api-client"])
        self.assertEqual(groups["bug"]["covered_in"], [])

    def test_overlapping_themes_are_counted_per_rejection(self):
        self.assertRustPassed("reasons::tests::overlapping_themes_are_counted_per_rejection")


class EstimateTest(RustTest, unittest.TestCase):
    """/api/project carries the time estimate: exactly what aaf.py's estimate() gives for the served
    workspace at the core's clock (`serve --clock`), plus aaf's calibration (how often past ranges held),
    cached briefly."""
    NOW = "2026-10-14T14:50:00+02:00"

    @classmethod
    def setUpClass(cls):
        cls.aaf = load_aaf("aaf_for_estimate")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(FIXTURES, "projects"), os.path.join(self.tmp, "projects"))
        self.srv = app_server.Served(self.tmp, clock=self.NOW)

    def tearDown(self):
        self.srv.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def estimate(self, name, base=None):
        return get_json(base or self.srv.base, "/api/project?name=" + name)["estimate"]

    def expected(self, root, name):
        """aaf.estimate() on <root>/projects/<name> with the clock at NOW (written here, not taken from the core)."""
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
            got = self.estimate(name)
            want, cal = self.expected(self.tmp, name)
            self.assertTrue(got.pop("available"), name)
            self.assertEqual(got.pop("held"), cal, name)
            self.assertEqual(got, want, name)
            active += want["active"]
        self.assertEqual(active, 4)  # data-pipeline, image-classifier, notes-app, web-scraper

    def test_scenarios(self):
        e = self.estimate("image-classifier")
        self.assertEqual(e["plan"], {"steps": 5, "done": 2, "current": "Retrain and compare validation accuracy"})
        self.assertLess(e["progress_low"], e["progress_high"])
        self.assertIn("past review and fixing", self.estimate("notes-app")["basis"])
        self.assertIn("longer than almost every", self.estimate("data-pipeline")["basis"])
        longest = max(t["duration_s"] or 0 for n in os.listdir(os.path.join(self.tmp, "projects"))
                      for t in self.aaf.task_stats(os.path.join(self.tmp, "projects", n))["tasks"] if t["outcome"] != "running")
        self.assertGreater(self.estimate("data-pipeline")["elapsed_s"], longest,
                           "data-pipeline runs longer than any task before it")
        held = self.estimate("brand-new")["held"]
        self.assertEqual((held["predictions_checked"], held["coverage"]), (10, 0.7))

    def test_no_history(self):
        root = os.path.join(PROJECT, "fixtures", "first-run")
        with app_server.serve(root, clock=self.NOW) as base:
            got = self.estimate("first-project", base)
        want, cal = self.expected(root, "first-project")
        self.assertEqual(got["remaining_low_s"], None)
        self.assertEqual(got["basis"], "too little history")
        self.assertEqual(got["held"]["predictions_checked"], 0)
        got.pop("available"), got.pop("held")
        self.assertEqual(got, want)

    def test_cached_briefly(self):
        first = self.estimate("notes-app")
        path = os.path.join(self.tmp, "projects", "notes-app", "state", "status.json")
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        st["phase"] = "done"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f)
        self.assertEqual(self.estimate("notes-app"), first, "asked again at once: from the cache")
        time.sleep(15.5)  # the cache time (15 s)
        self.assertEqual(self.estimate("notes-app")["active"], False, "after the cache time: fresh")

    def test_failed_run_is_not_repeated_on_every_poll(self):
        self.assertRustPassed("aaf::tests::failed_estimate_is_cached_briefly_not_retried_on_every_poll")

    def test_unavailable_without_aaf(self):
        self.assertRustPassed("aaf::tests::unavailable_without_aaf")


if __name__ == "__main__":
    unittest.main()
