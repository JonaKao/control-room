"""Notifications: the core notices, in every workspace of the settings, when something becomes true that
the human should hear about, once per change.

Through `control-room serve --config <temp>` with two copies of the fixtures, alpha (shown) and beta (not
shown). After the first look, files are changed the way aaf.py and the activity hook change them:
- alpha/api-client: Claude Code asks for permission (a new "waiting" step)      -> waiting
- alpha/data-pipeline: the phase becomes stuck                                 -> stuck
- alpha/example-done: a test run fails right after a passing one               -> failing
- beta/notes-app: a fix is set aside as a draft and the phase becomes waiting  -> decision (one, not two)
- beta/image-classifier: the review passes and the task ends done              -> finished
/api/events must then list exactly these five, one each, in plain words, with the right workspace; none
for what was already true at the start (parser waits for a decision, scheduler is stuck, web-scraper waits
for permission), none twice over the next looks, none after a restart for what is still true. A kind that
is switched off in the settings is still listed, but marked not to notify.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import app_server  # noqa: E402

FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
LOOK_S = 5  # the core looks every 5 s
problems = []


def events(base):
    return app_server.get_json(base, "/api/events")["events"]


def wait_events(base, n, seconds):
    deadline, got = time.time() + seconds, []
    while time.time() < deadline:
        got = events(base)
        if len(got) >= n:
            return got
        time.sleep(0.5)
    return got


def post(base, path, body):
    port = base.rsplit(":", 1)[1]
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-AAF-Request": "control-room",
                                          "Host": "127.0.0.1:" + port})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def set_status(pdir, phase, updated):
    with open(os.path.join(pdir, "state", "status.json"), "w", encoding="utf-8") as f:
        json.dump({"phase": phase, "task": "Notification test", "updated": updated}, f)


def append(path, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main():
    tmp = tempfile.mkdtemp(prefix="aaf-notify-")
    alpha, beta, config = os.path.join(tmp, "alpha"), os.path.join(tmp, "beta"), os.path.join(tmp, "config")
    shutil.copytree(FIXTURES, alpha)
    shutil.copytree(FIXTURES, beta)
    os.makedirs(config)
    with open(os.path.join(config, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"workspaces": [{"path": alpha, "name": "alpha"}, {"path": beta, "name": "beta"}], "current": alpha}, f)
    srv = None
    try:
        srv = app_server.Served(None, config=config)
        time.sleep(LOOK_S + 2)
        if events(srv.base):
            problems.append("start: events raised for what was already true: %s" % [(e["project"], e["kind"]) for e in events(srv.base)])

        a = lambda n: os.path.join(alpha, "projects", n)
        b = lambda n: os.path.join(beta, "projects", n)
        append(os.path.join(a("api-client"), "state", "activity.jsonl"),
               {"ts": "2026-10-15T10:00:00+02:00", "kind": "waiting", "text": "Waiting for your permission in Claude Code",
                "tool_use_id": "toolu_notify_1"})
        set_status(a("data-pipeline"), "stuck", "2026-10-15T10:01:00+02:00")
        append(os.path.join(a("example-done"), "state", "check_history.jsonl"),
               {"ran_at": "2026-10-15T10:04:00+02:00", "passed": False, "n_pass": 1, "n_total": 2})
        os.makedirs(os.path.join(b("notes-app"), "state", "drafts", "fix-9"))
        with open(os.path.join(b("notes-app"), "state", "drafts", "fix-9", "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "fix-9", "issue": "Flaky save test", "summary": "Timed out"}, f)
        set_status(b("notes-app"), "waiting", "2026-10-15T10:02:00+02:00")
        with open(os.path.join(b("image-classifier"), "state", "review.json"), "w", encoding="utf-8") as f:
            json.dump({"verdict": "pass", "summary": "Looks good"}, f)
        set_status(b("image-classifier"), "done", "2026-10-15T10:03:00+02:00")

        got = wait_events(srv.base, 5, 3 * LOOK_S)
        seen = sorted((e["workspace_name"], e["project"], e["kind"]) for e in got)
        want = sorted([("alpha", "api-client", "waiting"), ("alpha", "data-pipeline", "stuck"), ("alpha", "example-done", "failing"),
                       ("beta", "notes-app", "decision"), ("beta", "image-classifier", "finished")])
        if seen != want:
            problems.append("changes: events %s, expected exactly %s" % (seen, want))
        for e in got:
            if not e["notify"]:
                problems.append("changes: %s/%s is marked not to notify, though every kind is on" % (e["project"], e["kind"]))
            if e["project"] not in e["text"] or re.search(r"\.(json|jsonl|md|py)\b|\baaf\b|\bphase\b", e["text"]):
                problems.append("changes: the text is not plain words about the project: %r" % e["text"])
            if not os.path.samefile(e["workspace"], alpha if e["workspace_name"] == "alpha" else beta):
                problems.append("changes: %s names the wrong workspace folder %r" % (e["project"], e["workspace"]))
        texts = {e["kind"]: e["text"] for e in got}
        if texts.get("waiting") != "api-client is waiting for your permission in Claude Code":
            problems.append("changes: the permission wait reads %r" % texts.get("waiting"))

        time.sleep(2 * LOOK_S + 1)
        if len(events(srv.base)) != len(got):
            problems.append("twice: %d events after two more looks, %d before" % (len(events(srv.base)), len(got)))

        # A kind switched off: still listed, not notified.
        settings = post(srv.base, "/api/settings", {"notify": {"stuck": False}})
        if settings.get("notify", {}).get("stuck") is not False or settings["notify"].get("waiting") is not True:
            problems.append("switch: the settings did not keep 'stuck' off and the rest on: %r" % settings.get("notify"))
        set_status(b("data-pipeline"), "stuck", "2026-10-15T10:05:00+02:00")
        later = wait_events(srv.base, len(got) + 1, 3 * LOOK_S)
        new = [e for e in later if e["id"] not in {x["id"] for x in got}]
        if [(e["workspace_name"], e["project"], e["kind"], e["notify"]) for e in new] != [("beta", "data-pipeline", "stuck", False)]:
            problems.append("switch: a stuck project with stuck switched off gave %r" % [(e["project"], e["kind"], e["notify"]) for e in new])
        if later and later[0]["id"] != max(e["id"] for e in later):
            problems.append("order: /api/events is not newest first")

        # A restart: what is true now was true at its start, so nothing is raised.
        srv.stop()
        srv = app_server.Served(None, config=config)
        time.sleep(2 * LOOK_S + 1)
        if events(srv.base):
            problems.append("restart: events raised again after a restart: %s" % [(e["project"], e["kind"]) for e in events(srv.base)])
        if app_server.get_json(srv.base, "/api/settings")["notify"]["stuck"] is not False:
            problems.append("restart: the notification switch did not survive the restart")
    except Exception as e:
        problems.append("the notifications check stopped: %s" % str(e).splitlines()[0])
    finally:
        if srv:
            srv.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        print("FAIL: notifications:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: one event per change in both workspaces, none at the start, none twice, none after a restart, "
          "and a switched-off kind is listed without a notification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
