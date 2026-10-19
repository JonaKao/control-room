"""Check the time estimate ("How far along" in the hero, and how often estimates held in the track record).

Data: framework/aaf.py estimate() for the served workspace, with the server's clock pinned (server.CLOCK)
and the browser clock pinned to the same moment. For every fixture, in a headless browser:
- a running task shows a range, never a single number: "38–56%" ([data-est-range]), a bar whose solid
  part ends at progress_low and whose shaded band ([data-est-band]) runs from progress_low to
  progress_high, and "about 20 to 45 minutes left" ([data-est-left]) matching remaining_low/high_s;
- with a plan, "step 3 of 5" ([data-est-step]) and the current step's text;
- what the range is based on, in plain words, with the number of past tasks ([data-est-basis]):
  plan steps (image-classifier), review time (notes-app), running longer than almost every past
  task (data-pipeline), and "not enough history yet" with no range at all (fixtures/first-run);
- how often past estimates held, with the number checked ([data-est-held] in the hero,
  [data-est-record] in the track record), or that none has been checked yet;
- time left reads well from seconds to weeks (minutes, hours, then days; no "123.5 hours");
- a project without a running task shows no range and no time left; where the human is needed, the
  "what to do" card takes the hero's right half instead;
- no internal words (basis, calibration, coverage, file names), no sideways scrolling on phones,
  no JavaScript errors, in dark, light and phone views.
Screenshots: plots/render-estimate-*.png.
"""
import os
import re
import sys
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
FIRST_RUN = os.path.join(PROJECT, "fixtures", "first-run")
PLOTS = os.path.join(PROJECT, "plots")
NOW = "2026-10-14T14:50:00+02:00"
VIEWS = [("dark", 1440, 900, "dark"), ("light", 1440, 900, "light"), ("phone", 390, 844, "light")]
INTERNAL = re.compile(r"\b(basis|calibration|coverage|width_scale|progress_(low|high)|remaining_\w+|history_\w+"
                      r"|implementing|reviewing|checking|planning phase|iteration)\b|\b[\w-]+\.(json|jsonl|md|py)\b|\baaf\b", re.I)
# What each running fixture's "based on" sentence must say (written by hand from the fixtures).
BASIS = {"image-classifier": r"plan step", "notes-app": r"review", "data-pipeline": r"longer than almost every",
         "web-scraper": r"how long .*past tasks took", "first-project": r"not enough history yet"}
UNIT = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "min": 60, "hour": 3600, "hours": 3600,
        "day": 86400, "days": 86400}


def serve(root):
    server.set_root(root)
    server.CLOCK = NOW
    server._estimate_cache.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def open_page(browser, base, name, w, h, scheme):
    page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
    if scheme == "light":  # dark is the page's default; light is the choice the theme switch stores
        page.add_init_script("try { localStorage.setItem('aaf.theme', 'light'); } catch (e) {}")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.clock.set_fixed_time(datetime.fromisoformat(NOW))
    page.goto("%s/#p=%s" % (base, name))
    page.wait_for_selector('[data-slot="estimate"]', state="attached", timeout=15000)
    page.wait_for_timeout(400)
    return page, errors


def text(page, sel):
    el = page.query_selector(sel)
    return re.sub(r"\s+", " ", el.inner_text()).strip() if el else None


def durations(words):
    """'about 20 to 45 minutes left' / 'about 50 minutes to 2 hours left' -> (low_s, high_s)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(\w+)?\s+to\s+(\d+(?:\.\d+)?)\s*(\w+)\s+left", words or "")
    if not m:
        return None
    hi_unit = UNIT.get(m.group(4))
    lo_unit = UNIT.get(m.group(2)) if m.group(2) in UNIT else hi_unit
    if not (lo_unit and hi_unit):
        return None
    return float(m.group(1)) * lo_unit, float(m.group(3)) * hi_unit


def close(shown, want):
    """Rounded for reading: within 15 % or 2 minutes of aaf's number."""
    return abs(shown - want) <= max(120, want * 0.15)


def check_running(page, name, label, est, problems):
    slot = '[data-slot="estimate"]'
    where = "%s/%s: " % (name, label)
    if est.get("remaining_low_s") is None:
        if page.query_selector(slot + " [data-est-range]") or page.query_selector(slot + " [data-est-left]"):
            problems.append(where + "shows a range although there is not enough history")
        basis = text(page, slot + " [data-est-basis]") or ""
        if not re.search(BASIS[name], basis, re.I):
            problems.append(where + "does not say 'not enough history yet': %r" % basis)
    else:
        lo, hi = round(est["progress_low"] * 100), round(est["progress_high"] * 100)
        rng = text(page, slot + " [data-est-range]") or ""
        nums = [int(x) for x in re.findall(r"\d+", rng)]
        if nums[:2] != [lo, hi] or "%" not in rng:
            problems.append(where + "range shows %r, expected %d–%d%%" % (rng, lo, hi))
        bar = page.query_selector(slot + " [data-est-bar]")
        band = page.query_selector(slot + " [data-est-band]")
        fill = page.query_selector(slot + " [data-est-done]")
        if not (bar and band and fill):
            problems.append(where + "no progress bar with a shaded band")
        else:
            b, s, f = bar.bounding_box(), band.bounding_box(), fill.bounding_box()
            at = lambda x: (x - b["x"]) / b["width"] * 100  # noqa: E731
            if abs(at(f["x"] + f["width"]) - lo) > 1.5:
                problems.append(where + "solid bar ends at %.1f%%, expected %d%%" % (at(f["x"] + f["width"]), lo))
            if abs(at(s["x"]) - lo) > 1.5 or abs(at(s["x"] + s["width"]) - hi) > 1.5:
                problems.append(where + "band spans %.1f–%.1f%%, expected %d–%d%%"
                                % (at(s["x"]), at(s["x"] + s["width"]), lo, hi))
        left = text(page, slot + " [data-est-left]")
        got = durations(left)
        if not got:
            problems.append(where + "time left is not a range like 'about 20 to 45 minutes left': %r" % left)
        elif not (close(got[0], est["remaining_low_s"]) and close(got[1], est["remaining_high_s"])):
            problems.append(where + "time left %r does not match %d–%d s" % (left, est["remaining_low_s"], est["remaining_high_s"]))
        basis = text(page, slot + " [data-est-basis]") or ""
        if not re.search(BASIS[name], basis, re.I):
            problems.append(where + "'based on' does not say %r: %r" % (BASIS[name], basis))
        if not re.search(r"\b%d past tasks?\b" % est["history_tasks"], basis):
            problems.append(where + "'based on' does not name the %d past tasks: %r" % (est["history_tasks"], basis))
        if est["history_scope"] == "all projects" and "all projects" not in basis:
            problems.append(where + "'based on' does not say the past tasks come from all projects: %r" % basis)
    plan = est.get("plan")
    if plan:
        step = text(page, slot + " [data-est-step]") or ""
        n = min(plan["done"] + 1, plan["steps"])
        if not re.search(r"\bstep %d of %d\b" % (n, plan["steps"]), step, re.I):
            problems.append(where + "does not say 'step %d of %d': %r" % (n, plan["steps"], step))
        if plan["current"] and plan["current"] not in (text(page, slot) or ""):
            problems.append(where + "the current step %r is not shown" % plan["current"])
    cal = est["calibration"]
    held = text(page, slot + " [data-est-held]")
    if cal["predictions_checked"]:
        hits = round(cal["coverage"] * cal["predictions_checked"])
        if not held or not re.search(r"\b%d of %d\b" % (hits, cal["predictions_checked"]), held):
            problems.append(where + "hero does not say past estimates held %d of %d times: %r"
                            % (hits, cal["predictions_checked"], held))
    words = text(page, slot) or ""
    if re.search(r"\bfrom\b[^.]*\bfrom\b", text(page, slot + " [data-est-basis]") or ""):
        problems.append(where + "'based on' says 'from' twice: %r" % text(page, slot + " [data-est-basis]"))
    if not plan and re.search(r"\bplan\b", text(page, slot + " [data-est-basis]") or "", re.I):
        problems.append(where + "'based on' mentions a plan, but there is none")
    if re.search(r"\b\d+ (finished )?tasks have finished\b|once \d+ tasks", words):
        problems.append(where + "names a fixed history size the framework may change: %r" % words)
    if held and "all projects" not in held:
        problems.append(where + "'estimates held' does not say it covers all projects: %r" % held)
    if INTERNAL.search(words):
        problems.append(where + "internal words in 'How far along': %r" % INTERNAL.search(words).group(0))


def check_record(page, name, held, problems):
    rec = text(page, '[data-section="record"] [data-est-record]')
    if rec is None:
        problems.append("%s: the track record does not say how often time estimates held" % name)
    elif held["predictions_checked"]:
        hits = round(held["coverage"] * held["predictions_checked"])
        if not re.search(r"\b%d of %d\b" % (hits, held["predictions_checked"]), rec) \
                or "%d%%" % round(held["coverage"] * 100) not in rec:
            problems.append("%s: track record says %r, expected %d of %d (%d%%)"
                            % (name, rec, hits, held["predictions_checked"], round(held["coverage"] * 100)))
    elif not re.search(r"no time estimate .*checked .*yet", rec, re.I):
        problems.append("%s: track record should say no estimate has been checked yet: %r" % (name, rec))


def run(browser, root, names, problems):
    httpd, base = serve(root)
    try:
        for name in names:
            est = server.detail(name)["estimate"]
            if not est.get("available"):
                problems.append("%s: no estimate from the server" % name)
                continue
            for label, w, h, scheme in VIEWS:
                page, errors = open_page(browser, base, name, w, h, scheme)
                if errors:
                    problems.append("%s/%s: JavaScript errors: %s" % (name, label, "; ".join(errors[:3])))
                if page.evaluate("document.documentElement.scrollWidth") > w + 1:
                    problems.append("%s/%s: sideways scrolling" % (name, label))
                if est["active"] and page.query_selector(".hero.with-action"):
                    # The human is needed (web-scraper: Claude Code asks for permission), so the "what to do"
                    # card takes the hero's right half; how long is left then depends on them.
                    if not page.query_selector('[data-section="action"]'):
                        problems.append("%s/%s: estimate hidden, but no 'what to do' card in its place" % (name, label))
                elif est["active"]:
                    check_running(page, name, label, est, problems)
                else:
                    slot = text(page, '[data-slot="estimate"]') or ""
                    if page.query_selector('[data-slot="estimate"] [data-est-range]') or re.search(r"\bleft\b", slot):
                        problems.append("%s/%s: shows a time estimate although no task is running" % (name, label))
                if label != "phone":
                    check_record(page, "%s/%s" % (name, label), est["held"], problems)
                if est["active"] or name == "example-done":
                    hero = page.query_selector(".hero") or page.query_selector("body")
                    if label == "phone":
                        page.screenshot(path=os.path.join(PLOTS, "render-estimate-%s-phone.png" % name), full_page=False)
                    else:
                        hero.screenshot(path=os.path.join(PLOTS, "render-estimate-%s-%s.png" % (name, label)))
                page.close()
    finally:
        httpd.shutdown()


def main():
    os.makedirs(PLOTS, exist_ok=True)
    problems = []
    names = sorted(n for n in os.listdir(os.path.join(FIXTURES, "projects")) if not n.startswith("."))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        run(browser, FIXTURES, names, problems)
        run(browser, FIRST_RUN, ["first-project"], problems)
        # The whole first screen with an estimate, for comparing with design/mockup-dark.png.
        httpd, base = serve(FIXTURES)
        page, _ = open_page(browser, base, "image-classifier", 1440, 900, "dark")
        # Time left from seconds to weeks: readable (no "123.5 hours"), and still close to the numbers.
        for lo, hi in [(20, 400), (300, 2700), (3495, 7536), (5000, 40000), (444000, 1013000), (2 * 86400, 30 * 86400)]:
            words = page.evaluate("([a, b]) => leftWords(a, b)", [lo, hi])
            got = durations(words)
            if not got or not (close(got[0], lo) or lo < 60) or not close(got[1], hi):
                problems.append("time left for %d–%d s reads %r" % (lo, hi, words))
            elif re.search(r"\d\d+\.\d", words) or re.search(r"\b\d{3,} hours", words):
                problems.append("time left for %d–%d s is hard to read: %r" % (lo, hi, words))
        page.screenshot(path=os.path.join(PLOTS, "render-estimate-desktop-dark.png"))
        httpd.shutdown()
        browser.close()
    if problems:
        print("Time estimate check failed:")
        for x in problems:
            print("  - " + x)
        sys.exit(1)
    print("Time estimate check passed for %d fixtures and the first-run workspace; screenshots in plots/render-estimate-*.png"
          % len(names))


if __name__ == "__main__":
    main()
