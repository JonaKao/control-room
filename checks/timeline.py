"""Check the task timeline ("Where the time went") against the fixtures, with the browser clock pinned.

The data comes from framework/aaf.py task_stats (what `aaf.py stats <project>` prints). For every
fixture it checks, in a headless browser:
- the section ([data-section=timeline]) follows the track record, as in design/DESIGN.md, with an
  empty state when no task has run;
- one row per task ([data-task-row]), latest on top, each with its outcome ([data-outcome-mark]:
  finished, waiting for your decision, stuck, still running) and its working time beside the bar
  ([data-total]);
- each row is split into one segment per phase ([data-seg], in order), one colour per kind of phase,
  segment lengths proportional to their duration and bars on one shared scale;
- attempt boundaries are marked ([data-attempt-mark]) where a new attempt starts;
- a task that resumed after being stuck shows the pause as a break ([data-gap]);
- tapping a segment shows what happened in it ([data-seg-detail]): stage, attempt, times, test runs,
  review verdicts;
- a running task grows while time passes, without new data, and an open segment stays open;
- plain words in the rows and legend, and no sideways overflow at phone width.
Screenshots: plots/render-timeline-*.png.
"""
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
# Pinned "now": shortly after the newest fixture event (image-classifier, still testing).
NOW = "2026-10-14T14:50:00+02:00"
OUTCOME_WORDS = {"done": "Finished", "waiting": "Waits for your decision", "stuck": "Stuck", "running": "Still running"}
INTERNAL = re.compile(r"\b(iteration|implementing|checking|reviewing|phase)\b|\b[\w-]+\.(json|jsonl|md|py)\b|\baaf\b", re.I)


def stats(name):
    return server.task_stats(name)


def dur_words(seconds):
    m = max(0, int(seconds / 60 + 0.5))
    return "%d min" % m if m < 60 else "%d h%s" % (m // 60, " %d min" % (m % 60) if m % 60 else "")


def secs(a, b):
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()


def open_page(browser, base, name, now=NOW, w=1440, h=900, scheme="light"):
    page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
    if scheme == "light":  # dark is the page's default; light is the choice the theme switch stores
        page.add_init_script("try { localStorage.setItem('aaf.theme', 'light'); } catch (e) {}")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.clock.set_fixed_time(datetime.fromisoformat(now))
    page.goto("%s/#p=%s" % (base, name))
    page.wait_for_selector('[data-section="timeline"]', timeout=15000)
    page.wait_for_timeout(300)
    return page, errors


def rows_info(page):
    return page.eval_on_selector_all("[data-task-row]", """rows => rows.map(r => ({
        start: r.dataset.start, outcome: r.dataset.outcome,
        mark: (r.querySelector('[data-outcome-mark]') || {}).textContent || '',
        total: ((r.querySelector('[data-total]') || {}).textContent || '').trim(),
        bar: (r.querySelector('[data-bar]') || {getBoundingClientRect: () => ({width: 0})}).getBoundingClientRect().width,
        segs: [...r.querySelectorAll('[data-seg]')].map(s => ({phase: s.dataset.phase, it: s.dataset.iteration,
            w: s.getBoundingClientRect().width, bg: getComputedStyle(s).backgroundColor})),
        gaps: [...r.querySelectorAll('[data-gap]')].map(g => g.getAttribute('aria-label') || g.textContent),
        marks: [...r.querySelectorAll('[data-attempt-mark]')].map(m => m.textContent.trim()),
        overflow: r.scrollWidth - r.clientWidth}))""")


def expected_marks(task):
    seen, marks = 0, []
    for ph in task["phases"]:
        it = ph.get("iteration") or 0
        if ph["phase"] == "implementing" and it > seen:
            if seen:
                marks.append(str(it))
            seen = it
    return marks


def work_s(task, now):
    return sum(secs(p["start"], p["end"] or now) for p in task["phases"])


def check_project(browser, base, name, colours):
    bad = []
    data = stats(name)
    tasks = data.get("tasks") or []
    page, errors = open_page(browser, base, name)
    order = page.eval_on_selector_all("main [data-section]",
                                      "els => els.filter(e => e.parentElement.closest('[data-section]') === null)"
                                      ".map(e => e.dataset.section)")
    if "timeline" not in order:
        page.close()
        return ["no timeline section"]
    if "record" in order and order.index("timeline") != order.index("record") + 1:
        bad.append("timeline does not follow the track record (order %s)" % order)
    if not tasks:
        if not page.query_selector('[data-section="timeline"] [data-empty]'):
            bad.append("no empty state although no task has run")
        if page.query_selector("[data-task-row]"):
            bad.append("rows shown although no task has run")
        page.close()
        return bad + ["JavaScript errors: %s" % errors[:3]] if errors else bad
    rows = rows_info(page)
    if len(rows) != len(tasks):
        bad.append("%d rows for %d tasks" % (len(rows), len(tasks)))
    want = list(reversed(tasks))
    if [r["start"] for r in rows] != [t["start"] for t in want]:
        bad.append("rows not latest first: %s" % [r["start"] for r in rows])
    widest = max(work_s(t, NOW) for t in tasks)
    for r, t in zip(rows, want):
        label = "%s / %r" % (name, t["task"][:30])
        if r["outcome"] != t["outcome"]:
            bad.append("%s: outcome %r, expected %r" % (label, r["outcome"], t["outcome"]))
        if OUTCOME_WORDS[t["outcome"]].lower() not in r["mark"].lower():
            bad.append("%s: outcome mark says %r, expected %r" % (label, r["mark"], OUTCOME_WORDS[t["outcome"]]))
        if r["total"] != dur_words(work_s(t, NOW)):
            bad.append("%s: duration %r, expected %r" % (label, r["total"], dur_words(work_s(t, NOW))))
        got = [(s["phase"], s["it"]) for s in r["segs"]]
        exp = [(p["phase"], str(p.get("iteration") or 0)) for p in t["phases"]]
        if got != exp:
            bad.append("%s: segments %s, expected %s" % (label, got, exp))
            continue
        for s in r["segs"]:
            colours.setdefault(s["phase"], set()).add(s["bg"])
        if r["marks"] != expected_marks(t):
            bad.append("%s: attempt marks %s, expected %s" % (label, r["marks"], expected_marks(t)))
        # Proportions: big segments in one row share one seconds-per-pixel ratio.
        ratios = [s["w"] / secs(p["start"], p["end"] or NOW) for s, p in zip(r["segs"], t["phases"])
                  if secs(p["start"], p["end"] or NOW) >= 0.08 * widest]
        if ratios and max(ratios) > 1.12 * min(ratios):
            bad.append("%s: segment lengths not proportional to time (%.3f..%.3f px/s)" % (label, min(ratios), max(ratios)))
        stops = sum(1 for a, b in zip(t["phases"], t["phases"][1:]) if a["end"] and secs(a["end"], b["start"]) > 0)
        if len(r["gaps"]) != stops:
            bad.append("%s: %d pause breaks, expected %d" % (label, len(r["gaps"]), stops))
        if r["overflow"] > 1:
            bad.append("%s: row overflows by %d px" % (label, r["overflow"]))
    # One shared scale: rows without pauses have bar length proportional to working time.
    plain_rows = [(r, t) for r, t in zip(rows, want) if not r["gaps"]]
    if len(plain_rows) >= 2:
        ratios = [r["bar"] / work_s(t, NOW) for r, t in plain_rows if work_s(t, NOW) >= 0.2 * widest]
        if ratios and max(ratios) > 1.12 * min(ratios):
            bad.append("bars are not on one shared scale (%.4f..%.4f px/s)" % (min(ratios), max(ratios)))
    words = page.eval_on_selector('[data-section="timeline"]',
                                  "s => [...s.querySelectorAll('[data-task-head],[data-legend],[data-axis],[data-outcome-mark]')]"
                                  ".map(e => e.textContent).join(' ')")
    if INTERNAL.search(words):
        bad.append("internal term in the timeline: %r" % INTERNAL.search(words).group(0))
    legend = page.eval_on_selector_all("[data-legend] [data-legend-phase]", "els => els.map(e => e.dataset.legendPhase)")
    used = {p["phase"] for t in tasks for p in t["phases"]}
    if not used <= set(legend):
        bad.append("legend misses %s" % sorted(used - set(legend)))
    if errors:
        bad.append("JavaScript errors: %s" % errors[:3])
    page.close()
    return bad


def check_detail(browser, base):
    """Tapping a segment says what happened in it; tapping it again closes it."""
    bad = []
    page, _ = open_page(browser, base, "example-done")
    t = [x for x in stats("example-done")["tasks"] if x["outcome"] == "stuck"][0]
    seg = '[data-task-row][data-start="%s"] [data-seg][data-phase="checking"][data-iteration="1"]' % t["start"]
    if not page.query_selector(seg):
        page.close()
        return ["detail: no test segment for attempt 1 of the stuck task"]
    if page.query_selector("[data-seg-detail]"):
        bad.append("detail: shown before anything was tapped")
    page.click(seg)
    page.wait_for_timeout(200)
    det = page.query_selector("[data-seg-detail]")
    text = det.inner_text() if det else ""
    for want in ("Testing", "attempt 1", "1 of 2 tests passed", "4 min"):
        if want not in text:
            bad.append("detail: %r missing from %r" % (want, text[:200]))
    if page.get_attribute(seg, "aria-pressed") != "true":
        bad.append("detail: tapped segment not marked as selected")
    rev = '[data-task-row] [data-seg][data-phase="reviewing"]'
    page.locator(rev).first.click()
    page.wait_for_timeout(200)
    text = page.inner_text("[data-seg-detail]")
    if "approved" not in text.lower():
        bad.append("detail: review segment does not say the review approved: %r" % text[:200])
    if not re.search(r"\d{1,2}:\d{2}", text):
        bad.append("detail: no start/end time in %r" % text[:200])
    if len(page.query_selector_all("[data-seg-detail]")) != 1:
        bad.append("detail: more than one segment open at once")
    page.screenshot(path=os.path.join(PLOTS, "render-timeline-detail.png"))
    page.locator(rev).first.click()
    page.wait_for_timeout(200)
    if page.query_selector("[data-seg-detail]"):
        bad.append("detail: tapping the segment again does not close it")
    # A pause says how long the task stood still and why.
    if page.query_selector("[data-gap]"):
        page.locator("[data-gap]").first.click()
        page.wait_for_timeout(200)
        text = page.inner_text("[data-seg-detail]") if page.query_selector("[data-seg-detail]") else ""
        if "16 h" not in text or "stuck" not in text.lower():
            bad.append("detail: pause does not say it stood still 16 h after getting stuck: %r" % text[:200])
    else:
        bad.append("detail: example-done has no pause break")
    page.close()
    return bad


def check_live(browser, base):
    """The running task grows as time passes, without new data, and keeps the open segment."""
    bad = []
    page, _ = open_page(browser, base, "image-classifier")
    sel = '[data-task-row][data-outcome="running"]'
    before = rows_info(page)[0]
    page.click(sel + " [data-seg]:last-child")
    later = datetime.fromisoformat(NOW) + timedelta(minutes=20)
    page.clock.set_fixed_time(later)
    page.wait_for_timeout(6500)
    after = rows_info(page)[0]
    if after["outcome"] != "running":
        bad.append("live: running task is not on top")
    if not after["bar"] > before["bar"] + 5:
        bad.append("live: running bar did not grow (%.0f -> %.0f px)" % (before["bar"], after["bar"]))
    if after["total"] == before["total"]:
        bad.append("live: duration did not change (%r)" % after["total"])
    if not page.query_selector("[data-seg-detail]"):
        bad.append("live: the open segment closed when the bar grew")
    if not page.query_selector(sel + " [data-running-mark]"):
        bad.append("live: no 'still running' end on the running bar")
    page.close()
    return bad


def screenshots(browser, base):
    for label, w, h, scheme in [("desktop", 1440, 900, "light"), ("desktop-dark", 1440, 900, "dark"), ("phone", 390, 844, "light")]:
        page, _ = open_page(browser, base, "example-done", w=w, h=h, scheme=scheme)
        page.eval_on_selector('[data-section="timeline"]', "s => s.scrollIntoView()")
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(PLOTS, "render-timeline-%s.png" % label))
        page.close()


def main():
    server.set_root(FIXTURES)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.makedirs(PLOTS, exist_ok=True)
    names = sorted(n for n in os.listdir(os.path.join(FIXTURES, "projects")) if not n.startswith("."))
    problems, colours = [], {}
    needed = {"stuck": False, "resumed": False, "waiting": False, "running": False, "several": False}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in names:
            tasks = stats(name).get("tasks") or []
            needed["several"] |= len(tasks) >= 3
            needed["stuck"] |= any(t["outcome"] == "stuck" for t in tasks)
            needed["resumed"] |= any(t["times_stuck"] and t["outcome"] != "stuck" for t in tasks)
            needed["waiting"] |= any(t["outcome"] == "waiting" for t in tasks)
            needed["running"] |= any(t["outcome"] == "running" for t in tasks)
            problems += ["%s: %s" % (name, b) for b in check_project(browser, base, name, colours)]
            mobile, _ = open_page(browser, base, name, w=390, h=844)
            over = mobile.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            row_over = rows_info(mobile)
            if over > 1 or any(r["overflow"] > 1 for r in row_over):
                problems.append("%s/phone: timeline scrolls sideways" % name)
            mobile.close()
        problems += check_detail(browser, base)
        problems += check_live(browser, base)
        screenshots(browser, base)
        browser.close()
    httpd.shutdown()
    for phase, seen in colours.items():
        if len(seen) != 1:
            problems.append("phase %r drawn in %d colours" % (phase, len(seen)))
    flat = [next(iter(s)) for s in colours.values() if s]
    if len(set(flat)) != len(flat):
        problems.append("two kinds of phase share a colour: %s" % colours)
    problems += ["fixtures: no %s task" % k for k, v in needed.items() if not v]
    if problems:
        print("Timeline check FAILED:")
        for pr in problems:
            print("  - " + pr)
        sys.exit(1)
    print("Timeline check passed for %d fixtures; screenshots in plots/render-timeline-*.png" % len(names))


if __name__ == "__main__":
    main()
