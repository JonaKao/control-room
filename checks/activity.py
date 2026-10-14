"""Check the live activity feed against the fixtures, with the browser clock pinned.

The feed comes from state/activity.jsonl (written by framework/hooks/activity.py). For the
fixtures it checks, in a headless browser:
- every project has the live section ([data-section=live]) right after the summary (or after
  the "what to do" card when the human is needed), with an empty state when there is no log;
- the current step ([data-current-step]) is the newest entry, shown with an icon for its kind,
  and the summary has a short name-free "right now" line ([data-now]);
- a short recent history ([data-step], newest first, at most 8) with one icon per kind
  (different kinds, different icons); the full list of recent steps waits behind a closed block;
- steps taken by the reviewer helper agent are marked ([data-subagent=reviewer], "Reviewer");
- a latest "waiting" entry makes the human needed: summary flag, a "what to do" card naming
  Claude Code, and the project listed under "Needs you"; an idle prompt after a finished task
  does not;
- while a task is running, no step for several minutes says the feed has gone quiet
  ([data-quiet]), also when the time passes without new data; a recent step does not;
- plain words: framework file names and the framework tool are not shown;
- broken or unknown log lines do not break the page.
Screenshots: plots/render-activity-*.png.
"""
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
import server  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright is not installed. From projects/control-room run:\n"
          "  python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium")
    sys.exit(1)

FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
PLOTS = os.path.join(PROJECT, "plots")
FRAMEWORK_WORDS = re.compile(r"\b(DONE|CLAUDE|progress|decisions)\.md\b|\baaf\b|\.jsonl?\b")
HISTORY_MAX = 8


def log(name):
    rows = []
    try:
        with open(os.path.join(FIXTURES, "projects", name, "state", "activity.jsonl")) as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except OSError:
        pass
    return rows


def at(iso, minutes):
    return datetime.fromisoformat(iso) + timedelta(minutes=minutes)


def open_page(browser, base, name, now=None, w=1440, h=900, route=None):
    page = browser.new_page(viewport={"width": w, "height": h})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    if now is not None:
        page.clock.set_fixed_time(now)
    if route:
        page.route(*route)
    page.goto("%s/#p=%s" % (base, name))
    page.wait_for_selector('[data-section="live"]', timeout=15000)
    page.wait_for_timeout(300)
    return page, errors


def sections(page):
    return page.eval_on_selector_all("main [data-section]",
                                     "els => els.filter(e => e.parentElement.closest('[data-section]') === null)"
                                     ".map(e => e.dataset.section)")


def check_feed(page, name, rows):
    bad = []
    order = sections(page)
    needs = page.locator('[data-section="glance"] [data-needs]').first.get_attribute("data-needs")
    want_at = 2 if needs == "yes" else 1
    if "live" not in order or order.index("live") != want_at:
        bad.append("live section is at position %s of %s, expected %d"
                   % (order.index("live") if "live" in order else None, order, want_at))
    live = page.locator('[data-section="live"]')
    if not rows:
        if live.locator("[data-live-empty]").count() == 0:
            bad.append("no activity log, but no empty state ([data-live-empty])")
        return bad
    cur = live.locator("[data-current-step]")
    if cur.count() == 0:
        return bad + ["no current step ([data-current-step])"]
    newest = rows[-1]
    if cur.first.get_attribute("data-kind") != newest["kind"]:
        bad.append("current step kind %r, expected the newest entry's %r"
                   % (cur.first.get_attribute("data-kind"), newest["kind"]))
    if cur.first.locator("svg").count() == 0:
        bad.append("current step has no icon")
    now_line = page.locator('[data-section="glance"] [data-now]')
    if now_line.count() == 0 or not now_line.first.inner_text().strip():
        bad.append("summary has no 'right now' line ([data-now])")
    steps = live.locator("[data-step]")
    n = steps.count()
    want_n = min(HISTORY_MAX, len(rows) - 1)
    if n != want_n:
        bad.append("recent history shows %d steps, expected %d" % (n, want_n))
    kinds = [steps.nth(i).get_attribute("data-kind") for i in range(n)]
    expect = [r["kind"] for r in reversed(rows[:-1])][:want_n]
    if kinds != expect:
        bad.append("history kinds %s, expected newest first %s" % (kinds, expect))
    icons = {}
    for i in range(n):
        svg = steps.nth(i).locator("svg")
        if svg.count() == 0:
            bad.append("history step %d has no icon" % i)
            continue
        icons.setdefault(kinds[i], set()).add(svg.first.inner_html())
    flat = {k: next(iter(v)) for k, v in icons.items() if len(v) == 1}
    if len(set(flat.values())) != len(flat):
        bad.append("different kinds share the same icon: %s" % sorted(flat))
    for i in range(n):
        row = list(reversed(rows[:-1]))[i]
        marked = steps.nth(i).get_attribute("data-subagent")
        if row.get("subagent") == "reviewer":
            if marked != "reviewer" or "Reviewer" not in steps.nth(i).inner_text():
                bad.append("reviewer step %r is not marked as the reviewer's" % row["text"])
        elif marked:
            bad.append("step %r is marked as a helper agent's although it is not" % row["text"])
    more = live.locator('details[data-detail="steps"]')
    if len(rows) > 1 + HISTORY_MAX:
        if more.count() == 0:
            bad.append("more steps than the short history, but no block with the rest")
        elif more.first.get_attribute("open") is not None:
            bad.append("the full list of steps is open on load")
    text = live.inner_text() + " " + page.locator('[data-section="glance"]').inner_text()
    if page.locator('[data-section="action"]').count():
        text += " " + page.locator('[data-section="action"]').inner_text()
    if re.search(r"\bfor you for\b", text):
        bad.append("garbled wording: %r" % re.search(r"[^.]*\bfor you for\b[^.]*", text).group(0).strip())
    m = FRAMEWORK_WORDS.search(text)
    if m:
        bad.append("shows framework file or tool name %r" % m.group(0))
    return bad


def needed_in_rail(page, name):
    return page.evaluate("""n => { let g = null;
        for (const el of document.querySelectorAll('#projects .group-label, #projects .proj')) {
          if (el.classList.contains('group-label')) g = el.textContent.trim();
          else if (el.dataset.p === n) return g; }
        return null; }""", name)


def main():
    server.set_root(FIXTURES)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.makedirs(PLOTS, exist_ok=True)
    pdir = os.path.join(FIXTURES, "projects")
    names = sorted(n for n in os.listdir(pdir) if not n.startswith(".") and os.path.isdir(os.path.join(pdir, n)))
    problems = []
    if not [n for n in names if log(n) and log(n)[-1]["kind"] == "waiting"
            and json.load(open(os.path.join(pdir, n, "state", "status.json"))).get("phase") not in ("done", "idle")]:
        problems.append("no fixture where the agent waits for the human mid-task")
    if not any(r.get("subagent") == "reviewer" for n in names for r in log(n)):
        problems.append("no fixture with steps by the reviewer")
    if not [n for n in names if not log(n)]:
        problems.append("no fixture without an activity log (empty state)")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # Every fixture, one minute after its last step.
            for name in names:
                rows = log(name)
                now = at(rows[-1]["ts"], 1) if rows else None
                for label, w, h in (("desktop", 1440, 900), ("phone", 390, 844)):
                    page, errors = open_page(browser, base, name, now, w, h)
                    problems += ["%s/%s: %s" % (name, label, b) for b in check_feed(page, name, rows)]
                    problems += ["%s/%s: JavaScript error: %s" % (name, label, e) for e in errors[:3]]
                    if label == "phone" and page.evaluate("document.documentElement.scrollWidth - window.innerWidth") > 1:
                        problems.append("%s/phone: page scrolls sideways" % name)
                    if label == "phone" and page.locator("[data-now]").count():
                        top = page.eval_on_selector("[data-now]", "e => [e.querySelector('svg').getBoundingClientRect().top,"
                                                    " e.querySelector('span').getBoundingClientRect().top]")
                        if abs(top[0] - top[1]) > 8:
                            problems.append("%s/phone: the 'right now' icon sits on its own line" % name)
                    if name in ("web-scraper", "image-classifier", "example-done"):
                        page.locator('[data-section="live"]').first.scroll_into_view_if_needed()
                        page.screenshot(path=os.path.join(PLOTS, "render-activity-%s-%s.png" % (name, label)))
                    page.close()

            # Waiting for the human, mid-task.
            rows = log("web-scraper")
            page, _ = open_page(browser, base, "web-scraper", at(rows[-1]["ts"], 1))
            glance = page.locator('[data-section="glance"]')
            if glance.locator("[data-needs]").first.get_attribute("data-needs") != "yes" \
                    or "Claude Code" not in glance.locator("[data-needs]").first.inner_text():
                problems.append("web-scraper: summary does not say the human is needed in Claude Code")
            act = page.locator('[data-section="action"]')
            if act.count() == 0 or "Claude Code" not in act.first.inner_text() \
                    or "permission" not in act.first.inner_text().lower():
                problems.append("web-scraper: no 'what to do' card saying Claude Code asks for permission")
            if needed_in_rail(page, "web-scraper") != "Needs you":
                problems.append("web-scraper: project list puts it under %r, not 'Needs you'"
                                % needed_in_rail(page, "web-scraper"))
            if page.locator('[data-section="live"] [data-current-step][data-attention="yes"]').count() == 0:
                problems.append("web-scraper: the waiting step is not highlighted ([data-attention=yes])")
            page.close()

            # Idle prompt after a finished task: calm.
            rows = log("example-done")
            page, _ = open_page(browser, base, "example-done", at(rows[-1]["ts"], 1))
            if page.locator('[data-section="glance"] [data-needs]').first.get_attribute("data-needs") != "no":
                problems.append("example-done: an idle prompt after a finished task is shown as needing the human")
            cur = page.locator("[data-current-step]")
            if cur.count() and cur.first.get_attribute("data-attention") == "yes":
                problems.append("example-done: the idle prompt after a finished task is highlighted as urgent")
            if needed_in_rail(page, "example-done") == "Needs you":
                problems.append("example-done: listed under 'Needs you' for an idle prompt")
            page.close()

            # Quiet: a running task with no step for a while.
            rows = log("image-classifier")
            last = rows[-1]["ts"]
            page, _ = open_page(browser, base, "image-classifier", at(last, 1))
            if page.locator("[data-quiet]").count():
                problems.append("image-classifier: says the feed is quiet one minute after a step")
            page.clock.set_fixed_time(at(last, 20))
            try:
                page.wait_for_selector("[data-quiet]", timeout=40000)
                quiet = page.locator("[data-quiet]").first.inner_text()
                if "quiet" not in quiet.lower() or "20 min" not in quiet:
                    problems.append("image-classifier: quiet notice %r does not say it is quiet for 20 min" % quiet)
            except Exception:
                problems.append("image-classifier: 20 minutes without a step, but the page never says the feed went quiet")
            flag = page.locator('[data-section="glance"] [data-needs]').first.inner_text()
            if "keep going on its own" in flag:
                problems.append("image-classifier: quiet for 20 min, but the summary still says %r" % flag)
            page.locator('[data-section="live"]').first.scroll_into_view_if_needed()
            page.screenshot(path=os.path.join(PLOTS, "render-activity-quiet-desktop.png"))
            page.close()
            # Finished tasks are never "quiet", and the page is left alone while nothing changes
            # (a redraw would drop text the reader has selected).
            rows = log("example-done")
            page, _ = open_page(browser, base, "example-done", at(rows[-1]["ts"], 120))
            if page.locator("[data-quiet]").count():
                problems.append("example-done: a finished task is reported as quiet")
            page.eval_on_selector('[data-section="live"]', "e => { e.dataset.mark = 'kept'; }")
            page.clock.set_fixed_time(at(rows[-1]["ts"], 125))
            page.wait_for_timeout(3500)
            if page.locator('[data-section="live"][data-mark="kept"]').count() == 0:
                problems.append("example-done: the page redraws although nothing changed and no task is running")
            page.close()

            # Stuck, and Claude Code waits for a reply: the specific reason stays, red stays red.
            def stuck_waits(route):
                resp = route.fetch()
                d = resp.json()
                ask = {"ts": "2026-10-14T14:50:00+02:00", "kind": "waiting", "text": "Waiting for your reply in Claude Code"}
                if isinstance(d, list):
                    for p_ in d:
                        if p_["name"] == "scheduler":
                            p_["activity"] = ask
                else:
                    d["activity"] = [ask]
                    d["summary"]["activity"] = ask
                route.fulfill(response=resp, json=d)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.clock.set_fixed_time(at("2026-10-14T14:50:00+02:00", 1))
            page.route("**/api/project*", stuck_waits)
            page.goto("%s/#p=scheduler" % base)
            page.wait_for_selector('[data-section="live"]', timeout=15000)
            page.wait_for_timeout(300)
            flag = page.locator('[data-section="glance"] [data-needs]').first.inner_text()
            if "stuck" not in flag.lower():
                problems.append("scheduler: a waiting step hides that the project is stuck (flag says %r)" % flag)
            if "Claude Code" not in flag:
                problems.append("scheduler: stuck and Claude Code waits, but the flag does not mention Claude Code")
            if page.locator('#projects .proj[data-p="scheduler"] .dot.bad').count() == 0:
                problems.append("scheduler: a waiting step turns the stuck project's red dot into another colour")
            page.close()

            # Broken and unknown lines.
            def patch(route):
                resp = route.fetch()
                d = resp.json()
                d["activity"] = [{"kind": "mystery"}, {"ts": "not a time", "text": 42}, {},
                                 {"ts": "2026-10-14T14:50:00+02:00", "kind": "brand-new-kind", "text": "Doing <b>x</b>"}]
                route.fulfill(response=resp, json=d)
            page, errors = open_page(browser, base, "image-classifier", at(last, 1),
                                     route=("**/api/project?name=image-classifier", patch))
            if errors:
                problems.append("odd log lines: JavaScript error: %s" % errors[0])
            if page.locator("[data-current-step] b").count():
                problems.append("odd log lines: step text is not escaped")
            page.close()
            browser.close()
    except Exception as e:
        problems.append("page did not get through the activity checks: %s" % str(e).splitlines()[0])
    finally:
        httpd.shutdown()
    if problems:
        print("FAILED (%d):\n- %s" % (len(problems), "\n- ".join(problems)))
        sys.exit(1)
    print("Activity feed: current step, recent history, reviewer marks, waiting and quiet states work")


if __name__ == "__main__":
    main()
