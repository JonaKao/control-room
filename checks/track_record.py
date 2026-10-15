"""Check the track record ("Track record" per project, "All projects" for the workspace), clock pinned.

Data: framework/aaf.py task_stats (what `aaf.py stats <project>` prints) and state/review_history.jsonl.
For every fixture it checks, in a headless browser:
- the section ([data-section=record]) comes after the task timeline, with an empty state when no task ran;
- the four numbers ([data-kpi]): right the first time (of the tasks that ended), reviews that said no (of
  all reviews), fixes set aside, times stuck, equal aaf.py's summary; aaf.py counts stuck and waiting tasks
  as ended ("finished"), so where some are, the page must not call them finished tasks (also in the workspace);
- the attempts chart: one bar per task ([data-trend-col]) oldest first, height in proportion to its
  attempts, one colour per outcome; under each bar one mark per review (said no / approved), per fix set
  aside and per time stuck;
- tapping a bar shows the task, and why the review said no while it ran; tapping again closes it;
- "Why the review said no": the reasons ([data-reason]) most common first with their counts, matched to
  the definition of done where it already covers them (api-client: the progress note, three times), an
  "Other" group for summaries that fit no theme (parser), and an empty state where no review said no;
- plain words: no file names or internal terms in the section, no sideways scrolling on phones.
The workspace view ("All projects" in the project list, also reachable as #p=*): totals over all projects,
one row per project with tasks (most trouble first), reasons that say which projects' definition of done
already covers them, a note when one review named several reasons, the projects without tasks named, the most common
reasons across projects with where they were seen, a lead sentence naming the top reason, and a tap on a
project name opens it. A workspace where no task ran says so.
Screenshots: plots/render-record-*.png.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from datetime import datetime
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
NOW = "2026-10-14T14:50:00+02:00"
INTERNAL = re.compile(r"\b(iteration|implementing|checking|reviewing|phase|first_try|review_fails|times_stuck)\b"
                      r"|\b[\w-]+\.(json|jsonl|md|py)\b|\baaf\b", re.I)
# Written by hand from the fixtures' review summaries, not from the server's grouping.
REASONS = {"api-client": [("progress", 3), ("weakened", 1), ("coverage", 1), ("bug", 1)], "parser": [("other", 1)]}


def serve(root):
    server.set_root(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def open_page(browser, base, name, w=1440, h=900, scheme="light", wait='[data-section="record"]'):
    page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.clock.set_fixed_time(datetime.fromisoformat(NOW))
    page.goto("%s/#p=%s" % (base, name))
    page.wait_for_selector(wait, timeout=15000)
    page.wait_for_timeout(300)
    return page, errors


def kpis(page, scope):
    return page.eval_on_selector_all(scope + " [data-kpi]", """els => Object.fromEntries(els.map(e =>
        [e.dataset.kpi, e.querySelector('.kv').textContent.replace(/\\s+/g, ' ').trim()]))""")


def want_kpis(s):
    return {"first-try": "%d of %d" % (s.get("first_try", 0), s.get("finished", 0)),
            "rejected": "%d of %d" % (s.get("review_fails", 0), s.get("reviews", 0)),
            "drafts": str(s.get("drafts", 0)), "stuck": str(s.get("times_stuck", 0))}


def reasons_in(page, scope):
    return page.eval_on_selector_all(scope + " [data-reason]", """els => els.map(e => ({key: e.dataset.reason,
        count: +e.dataset.count, n: e.querySelector('.rn').textContent.trim(), text: e.innerText}))""")


def check_project(browser, base, name, colours):
    bad = []
    st = server.task_stats(name)
    tasks, s = st.get("tasks") or [], st.get("summary") or {}
    page, errors = open_page(browser, base, name)
    order = page.eval_on_selector_all("main [data-section]",
                                      "els => els.filter(e => e.parentElement.closest('[data-section]') === null)"
                                      ".map(e => e.dataset.section)")
    if "timeline" in order and order.index("record") < order.index("timeline"):
        bad.append("track record comes before the task timeline (order %s)" % order)
    sec = '[data-section="record"]'
    if not tasks:
        if not page.query_selector(sec + " [data-empty]"):
            bad.append("no empty state although no task has run")
        if page.query_selector(sec + " [data-trend-col]"):
            bad.append("attempts chart shown although no task has run")
        page.close()
        return bad + (["JavaScript errors: %s" % errors[:3]] if errors else [])

    if s.get("finished", 0) != s.get("done", 0):
        # aaf.py counts stuck and waiting tasks as ended ("finished"); the page must not call them finished.
        said = page.eval_on_selector(sec, "s => s.querySelector('[data-kpi=\"first-try\"] .kd').textContent + ' ' +"
                                          " (s.querySelector('.rec-cap') || {}).textContent")
        if re.search(r"\bfinished (task|tasks|ones)\b", said):
            bad.append("calls stuck or waiting tasks finished: %r" % said[:200])
    got = kpis(page, sec)
    if got != want_kpis(s):
        bad.append("numbers %s, expected %s (aaf.py stats summary)" % (got, want_kpis(s)))

    cols = page.eval_on_selector_all(sec + " [data-trend-col]", """els => els.map(e => ({start: e.dataset.start,
        attempts: +e.dataset.attempts, outcome: e.dataset.outcome, h: e.querySelector('.b').getBoundingClientRect().height,
        bg: getComputedStyle(e.querySelector('.b')).backgroundColor}))""")
    if [c["start"] for c in cols] != [t["start"] for t in tasks[-30:]]:
        bad.append("chart bars %s are not the tasks oldest first" % [c["start"] for c in cols])
    elif [c["attempts"] for c in cols] != [t["attempts"] for t in tasks[-30:]]:
        bad.append("chart attempts %s, expected %s" % ([c["attempts"] for c in cols], [t["attempts"] for t in tasks[-30:]]))
    ratios = [c["h"] / c["attempts"] for c in cols if c["attempts"]]
    if ratios and max(ratios) > 1.08 * min(ratios):
        bad.append("bar heights not in proportion to attempts (%.1f..%.1f px per attempt)" % (min(ratios), max(ratios)))
    for c in cols:
        colours.setdefault(c["outcome"], set()).add(c["bg"])
    marks = page.eval_on_selector(sec, """s => ({fail: s.querySelectorAll('[data-review-mark=fail]').length,
        pass: s.querySelectorAll('[data-review-mark=pass]').length, drafts: s.querySelectorAll('[data-draft-mark]').length,
        stuck: s.querySelectorAll('[data-stuck-mark]').length})""")
    want = {"fail": s.get("review_fails", 0), "pass": s.get("reviews", 0) - s.get("review_fails", 0),
            "drafts": s.get("drafts", 0), "stuck": s.get("times_stuck", 0)}
    if marks != want:
        bad.append("marks under the bars %s, expected %s" % (marks, want))

    got = reasons_in(page, sec)
    exp = REASONS.get(name, [])
    if [(r["key"], r["count"]) for r in got] != exp:
        bad.append("reasons %s, expected %s" % ([(r["key"], r["count"]) for r in got], exp))
    if any(str(r["count"]) != r["n"] for r in got):
        bad.append("a reason shows a different number than it counts")
    if not exp and not page.query_selector(sec + " [data-reasons-empty]"):
        bad.append("no 'the review has not said no' state although no review said no")
    if name == "api-client" and got:
        if "definition of done already asks" not in got[0]["text"] or "progress note" not in got[0]["text"]:
            bad.append("api-client: top reason does not point to the definition-of-done item: %r" % got[0]["text"][:300])
        bug = [r for r in got if r["key"] == "bug"]
        if bug and "definition of done already" in bug[0]["text"]:
            bad.append("api-client: 'bug' claims to be in the definition of done")
    words = page.eval_on_selector(sec, "s => s.textContent")  # also the summaries in closed blocks
    if INTERNAL.search(words):
        bad.append("internal term in the track record: %r" % INTERNAL.search(words).group(0))
    if errors:
        bad.append("JavaScript errors: %s" % errors[:3])
    page.close()

    mobile, errors = open_page(browser, base, name, w=390, h=844)
    if mobile.evaluate("document.documentElement.scrollWidth - window.innerWidth") > 1:
        bad.append("phone: page scrolls sideways")
    over = mobile.eval_on_selector(sec, "s => s.scrollWidth - s.clientWidth")
    if over > 1:
        bad.append("phone: track record overflows by %d px" % over)
    if errors:
        bad.append("phone: JavaScript errors: %s" % errors[:3])
    mobile.close()
    return bad


def check_tap(browser, base):
    """Tapping a bar shows the task and why the review said no during it; tapping again closes it."""
    bad = []
    page, _ = open_page(browser, base, "api-client")
    t = [x for x in server.task_stats("api-client")["tasks"] if x["task"] == "Async client"][0]
    col = '[data-trend-col][data-start="%s"]' % t["start"]
    if page.query_selector("[data-trend-detail]"):
        bad.append("tap: detail shown before anything was tapped")
    page.click(col)
    page.wait_for_timeout(200)
    det = page.query_selector("[data-trend-detail]")
    text = det.inner_text() if det else ""
    for want in ("Async client", "4 attempts", "said no twice", "what is next", "race when two requests"):
        if want.lower() not in text.lower():
            bad.append("tap: %r missing from the detail %r" % (want, text[:300]))
    for other in ("Model test skipped", "Resumed uploads"):
        if other.lower() in text.lower():
            bad.append("tap: detail lists another task's review: %r" % other)
    if page.get_attribute(col, "aria-pressed") != "true":
        bad.append("tap: tapped bar not marked as selected")
    if page.evaluate("document.activeElement && document.activeElement.dataset.start") != t["start"]:
        bad.append("tap: keyboard focus left the tapped bar")
    page.locator('[data-section="record"]').scroll_into_view_if_needed()
    page.screenshot(path=os.path.join(PLOTS, "render-record-detail.png"))
    page.click(col)
    page.wait_for_timeout(200)
    if page.query_selector("[data-trend-detail]"):
        bad.append("tap: tapping the bar again does not close the detail")
    page.close()
    return bad


def check_workspace(browser, base):
    bad = []
    names = server.project_names()
    stats = {n: server.task_stats(n) for n in names}
    page, errors = open_page(browser, base, "parser")
    ws = page.query_selector("#projects [data-workspace]")
    if not ws:
        page.close()
        return ["workspace: no 'All projects' entry in the project list"]
    ws.click()
    page.wait_for_selector('[data-section="ws-summary"]', timeout=10000)
    page.wait_for_timeout(300)
    total = {k: sum(stats[n]["summary"].get(k, 0) or 0 for n in names)
             for k in ("first_try", "finished", "review_fails", "reviews", "drafts", "times_stuck")}
    if total["finished"] != sum(stats[n]["summary"].get("done", 0) or 0 for n in names):
        said = page.eval_on_selector('[data-section="ws-summary"] [data-kpi="first-try"] .kd', "e => e.textContent")
        if re.search(r"\bfinished (task|tasks|ones)\b", said) or "stuck" not in said:
            bad.append("workspace: calls stuck or waiting tasks finished: %r" % said)
    got = kpis(page, '[data-section="ws-summary"]')
    if got != want_kpis(total):
        bad.append("workspace: totals %s, expected %s" % (got, want_kpis(total)))
    rows = page.eval_on_selector_all("[data-ws-project]", "els => els.map(e => e.dataset.wsProject)")
    busy = [n for n in names if stats[n]["tasks"]]
    trouble = lambda n: stats[n]["summary"].get("review_fails", 0) + stats[n]["summary"].get("times_stuck", 0)
    if rows != sorted(busy, key=lambda n: (-trouble(n), n)):
        bad.append("workspace: rows %s, expected %s (most trouble first)" % (rows, sorted(busy, key=lambda n: (-trouble(n), n))))
    for n in busy:
        cell = page.query_selector('[data-ws-project="%s"] [data-ws-first-try] b' % n)
        s = stats[n]["summary"]
        want_cell = "%d of %d" % (s["first_try"], s["finished"]) if s["finished"] else "No finished task yet"
        if not cell or cell.inner_text().strip() != want_cell:
            bad.append("workspace: %s first-try %r" % (n, cell.inner_text() if cell else None))
        spark = page.eval_on_selector_all('[data-ws-project="%s"] [data-ws-spark] span' % n, "e => e.length")
        if spark != len(stats[n]["tasks"][-30:]):
            bad.append("workspace: %s sparkline has %d bars for %d tasks" % (n, spark, len(stats[n]["tasks"])))
    idle = [n for n in names if not stats[n]["tasks"]]
    none = page.inner_text("[data-ws-none]") if page.query_selector("[data-ws-none]") else ""
    if any(n not in none for n in idle):
        bad.append("workspace: projects without tasks not named (%r)" % none)
    got = reasons_in(page, '[data-section="ws-reasons"]')
    if [(r["key"], r["count"]) for r in got] != [("progress", 3), ("weakened", 1), ("coverage", 1), ("bug", 1), ("other", 1)]:
        bad.append("workspace: reasons %s" % [(r["key"], r["count"]) for r in got])
    elif "api-client" not in got[0]["text"] or "parser" not in got[-1]["text"]:
        bad.append("workspace: reasons do not say which projects they come from")
    elif "definition of done of api-client already asks" not in got[0]["text"]:
        bad.append("workspace: the progress-note reason does not say api-client's definition of done covers it: %r"
                   % got[0]["text"][:300])
    lead = page.inner_text("[data-ws-lead]")
    if "progress note" not in lead.lower():
        bad.append("workspace: lead sentence does not name the most common reason: %r" % lead)
    words = page.text_content("main")
    if INTERNAL.search(words):
        bad.append("workspace: internal term %r" % INTERNAL.search(words).group(0))
    if errors:
        bad.append("workspace: JavaScript errors: %s" % errors[:3])
    if not re.search(r"#p=(\*|%2A)", page.url):
        bad.append("workspace: address does not remember the view (%s)" % page.url)
    page.click('[data-open="api-client"]')
    page.wait_for_selector('[data-section="glance"] .pname', timeout=10000)
    if page.inner_text('[data-section="glance"] .pname') != "api-client":
        bad.append("workspace: tapping a project name does not open it")
    page.close()

    for label, w, h, scheme in [("desktop", 1440, 900, "light"), ("desktop-dark", 1440, 900, "dark"), ("phone", 390, 844, "light")]:
        page, errors = open_page(browser, base, "*", w, h, scheme, wait='[data-section="ws-reasons"]')
        if page.evaluate("document.documentElement.scrollWidth - window.innerWidth") > 1:
            bad.append("workspace/%s: page scrolls sideways" % label)
        if errors:
            bad.append("workspace/%s: JavaScript errors: %s" % (label, errors[:3]))
        page.screenshot(path=os.path.join(PLOTS, "render-record-workspace-%s.png" % label), full_page=True)
        page.close()
    return bad


def check_empty_workspace(browser):
    """A workspace where no task has run yet says so, and shows no rows or reasons."""
    tmp = tempfile.mkdtemp(prefix="aaf-record-")
    try:
        shutil.copytree(os.path.join(FIXTURES, "projects", "brand-new"), os.path.join(tmp, "projects", "brand-new"))
        httpd, base = serve(tmp)
        page, errors = open_page(browser, base, "*", wait='[data-section="ws-summary"]')
        bad = []
        if "no project has run a task yet" not in page.inner_text("main").lower():
            bad.append("empty workspace: does not say that no task has run")
        if page.query_selector("[data-ws-project]") or page.query_selector("[data-reason]"):
            bad.append("empty workspace: shows rows or reasons")
        if not page.query_selector("[data-reasons-empty]"):
            bad.append("empty workspace: no 'the review has not said no' state")
        bad += ["empty workspace: JavaScript error: %s" % e for e in errors[:3]]
        page.close()
        httpd.shutdown()
        return bad
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_overlap(browser):
    """When one review names two reasons, the list says the counts add up to more than the rejections."""
    tmp = tempfile.mkdtemp(prefix="aaf-record-")
    try:
        for n in ("parser", "brand-new"):
            shutil.copytree(os.path.join(FIXTURES, "projects", n), os.path.join(tmp, "projects", n))
        with open(os.path.join(tmp, "projects", "parser", "state", "review_history.jsonl"), "w") as f:
            f.write(json.dumps({"at": "2026-10-14T12:15:00+02:00", "verdict": "fail",
                                "summary": "Progress note not updated, and a crash on empty input"}) + "\n")
        httpd, base = serve(tmp)
        bad = []
        for name, sec in (("parser", '[data-section="record"]'), ("*", '[data-section="ws-reasons"]')):
            page, errors = open_page(browser, base, name, wait=sec)
            keys = [r["key"] for r in reasons_in(page, sec)]
            note = page.query_selector(sec + " [data-reasons-overlap]")
            text = note.inner_text() if note else ""
            if keys != ["progress", "bug"] or "these 2 " not in text or "the 1 time the review" not in text:
                bad.append("overlap/%s: reasons %s, note %r (expected both reasons and a note: 2 add up to more than 1)"
                           % (name, keys, text))
            bad += ["overlap/%s: JavaScript error: %s" % (name, e) for e in errors[:3]]
            page.close()
        httpd.shutdown()
        return bad
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def screenshots(browser, base):
    for label, w, h, scheme in [("desktop", 1440, 900, "light"), ("desktop-dark", 1440, 900, "dark"), ("phone", 390, 844, "light")]:
        page, _ = open_page(browser, base, "api-client", w, h, scheme)
        page.eval_on_selector('[data-section="record"]', "s => s.previousElementSibling.scrollIntoView()")
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(PLOTS, "render-record-%s.png" % label))
        page.close()


def main():
    httpd, base = serve(FIXTURES)
    os.makedirs(PLOTS, exist_ok=True)
    names = server.project_names()
    problems, colours = [], {}
    if not any(server.task_stats(n)["summary"].get("review_fails") for n in names):
        problems.append("fixtures: no project where the review said no")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in names:
            problems += ["%s: %s" % (name, b) for b in check_project(browser, base, name, colours)]
        problems += check_tap(browser, base)
        problems += check_workspace(browser, base)
        screenshots(browser, base)
        httpd.shutdown()
        problems += check_empty_workspace(browser)
        problems += check_overlap(browser)
        browser.close()
    for outcome, seen in colours.items():
        if len(seen) != 1:
            problems.append("outcome %r drawn in %d colours" % (outcome, len(seen)))
    flat = [next(iter(s)) for s in colours.values() if s]
    if len(set(flat)) != len(flat):
        problems.append("two outcomes share a colour: %s" % colours)
    if problems:
        print("Track record check FAILED:")
        for pr in problems:
            print("  - " + pr)
        sys.exit(1)
    print("Track record check passed for %d fixtures and the workspace view; screenshots in plots/render-record-*.png"
          % len(names))


if __name__ == "__main__":
    main()
