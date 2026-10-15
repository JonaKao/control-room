"""Check that the page answers the two newcomer questions at a glance, for every fixture.

For each fixture project, at desktop (1440x900) and phone (390x844) size:
- The first section of the page is the "at a glance" summary, and it fits on the first
  screen without scrolling.
- It says what the agent is doing ([data-doing]) and whether the human is needed
  ([data-needs] = yes|no, which must match the fixture's real situation).
- It uses plain language: no file names and no internal terms.
- It shows the agent's loop as a picture ([data-viz=loop]).
- When something needs the human, the very next section says what to do ([data-section=action]).
- Health is shown visually: tests ([data-viz=checks]) and attempts used ([data-viz=attempts])
  whenever checks have run; the test history ([data-viz=history]) whenever there is one.
- Detail is on demand: decisions, progress note and activity log sit in closed <details>
  blocks, raw output (<pre>) is hidden at first, and opening a block shows its content.
- The project list says how many projects need the human ([data-overview-needs]).
"""
import json
import os
import re
import sys
import threading
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
VIEWS = [("desktop", 1440, 900), ("phone", 390, 844)]
# Whether each fixture's situation needs the human.
NEEDS = {"api-client": "no", "brand-new": "no", "example-done": "no", "image-classifier": "no", "parser": "yes", "scheduler": "yes",
         "web-scraper": "yes"}

def fixture_has(name, state_file):
    return os.path.isfile(os.path.join(FIXTURES, "projects", name, "state", state_file))
FILE_NAME = re.compile(r"\b[\w-]+\.(json|jsonl|md|py)\b")
INTERNAL = ("iteration", "implementing", "phase", "aaf")


def fixture_json(name, rel):
    try:
        with open(os.path.join(FIXTURES, "projects", name, rel)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def check_outcome(page, name):
    """The loop picture and the action card describe how the work ended, from the data."""
    bad = []
    st = fixture_json(name, "state/status.json")
    phase, it = st.get("phase"), st.get("iteration") or 0
    max_it = fixture_json(name, "project.json").get("max_iterations")
    steps = page.locator('[data-viz="loop"] li')
    if phase in ("done", "waiting", "stuck"):
        hint = steps.last.locator(".hint").inner_text().strip() if steps.count() else ""
        if not hint or hint == "done or ask you":
            bad.append("last loop step keeps its generic hint %r although the outcome is known" % hint)
    if phase == "stuck" and it:
        reached = page.eval_on_selector_all('[data-viz="loop"] li', "els => els.slice(0, 4).filter("
                                            "e => e.classList.contains('past') || e.classList.contains('tried')).length")
        if reached < 4:
            bad.append("stuck after %d attempts, but the loop picture shows only %d of Plan/Change/Test/Review as reached"
                       % (it, reached))
        card = page.locator('[data-section="action"]').inner_text() if page.locator('[data-section="action"]').count() else ""
        if max_it and it >= max_it and "all %d attempts" % max_it not in card:
            bad.append("stuck at the attempt limit, but the action card does not say it used all %d attempts" % max_it)
    return bad


def visible(page, sel):
    loc = page.locator(sel)
    return loc.count() > 0 and loc.first.is_visible()


def check_view(page, name, label, h):
    bad = []
    order = page.eval_on_selector_all("main [data-section]",
                                      "els => els.filter(e => e.parentElement.closest('[data-section]') === null)"
                                      ".map(e => e.dataset.section)")
    if not order or order[0] != "glance":
        return ["%s/%s: first section is %r, expected 'glance'" % (name, label, order[:1])]
    box = page.locator('[data-section="glance"]').bounding_box()
    if box["y"] + box["height"] > h + 1:
        bad.append("glance summary does not fit on the first screen (ends at %dpx, screen is %dpx)"
                   % (box["y"] + box["height"], h))
    glance = page.locator('[data-section="glance"]')
    doing = glance.locator("[data-doing]")
    if doing.count() == 0 or not doing.first.inner_text().strip():
        bad.append("glance does not say what the agent is doing ([data-doing])")
    needs = glance.locator("[data-needs]")
    got = needs.first.get_attribute("data-needs") if needs.count() else None
    if got != NEEDS[name]:
        bad.append("needs-you flag is %r, expected %r" % (got, NEEDS[name]))
    elif not needs.first.inner_text().strip():
        bad.append("needs-you flag has no text")
    text = glance.inner_text()
    if FILE_NAME.search(text):
        bad.append("glance shows a file name: %r" % FILE_NAME.search(text).group(0))
    for term in INTERNAL:
        if term in text.lower():
            bad.append("glance uses internal term %r" % term)
    if not visible(page, '[data-section="glance"] [data-viz="loop"]'):
        bad.append("glance has no loop picture ([data-viz=loop])")
    if NEEDS[name] == "yes" and (len(order) < 2 or order[1] != "action"):
        bad.append("needs the human, but the second section is %r, not 'action'" % (order[1:2],))
    if NEEDS[name] == "no" and "action" in order:
        bad.append("shows an action section although nothing needs the human")
    if fixture_has(name, "checks.json"):
        for viz in ("checks", "attempts"):
            if not visible(page, '[data-viz="%s"]' % viz):
                bad.append("no visual for %s ([data-viz=%s])" % (viz, viz))
    if fixture_has(name, "check_history.jsonl") and not visible(page, '[data-viz="history"]'):
        bad.append("no visual for test history ([data-viz=history])")
    for d in ("decisions", "progress", "activity"):
        loc = page.locator('details[data-detail="%s"]' % d)
        if loc.count() == 0:
            bad.append("no collapsible block for %s (details[data-detail=%s])" % (d, d))
        elif loc.first.get_attribute("open") is not None:
            bad.append("%s block is open on load; detail should be on demand" % d)
    shown_pre = page.eval_on_selector_all("main pre", "els => els.filter(e => e.checkVisibility()).length")
    if shown_pre:
        bad.append("%d raw output block(s) visible on load" % shown_pre)
    act = page.locator('details[data-detail="activity"]')
    if act.count():
        act.first.locator("summary").first.click()
        page.wait_for_timeout(100)
        body = act.first.inner_text().strip()
        summary = act.first.locator("summary").first.inner_text().strip()
        if act.first.get_attribute("open") is None or len(body) <= len(summary):
            bad.append("opening the activity block shows nothing")
    bad += check_outcome(page, name)
    ov = page.locator("[data-overview-needs]")
    want = str(sum(v == "yes" for v in NEEDS.values()))
    if ov.count() == 0 or ov.first.get_attribute("data-overview-needs") != want:
        bad.append("project list does not say that %s projects need the human ([data-overview-needs])" % want)
    return ["%s/%s: %s" % (name, label, b) for b in bad]


JARGON_NOTE = ("Implementing (iteration 2): updated progress.md and decisions.md; 2/3 checks pass, draft fix-1 saved; "
               "ran aaf.py check, wrote state/status.json")
JARGON_TASK = "Make DONE.md items hold (see project.json)"


def check_agent_words(browser, base):
    """Agent-written text in the summary is reworded: no framework terms or framework file names."""
    def patch(route):
        resp = route.fetch()
        d = resp.json()
        d["status"]["note"], d["status"]["task"] = JARGON_NOTE, JARGON_TASK
        route.fulfill(response=resp, json=d)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.route("**/api/project?name=image-classifier", patch)
    page.goto("%s/#p=image-classifier" % base)
    page.wait_for_timeout(1000)
    text = page.locator('[data-section="glance"]').inner_text()
    page.close()
    bad = []
    if FILE_NAME.search(text):
        bad.append("agent note shown with a framework file name: %r" % FILE_NAME.search(text).group(0))
    for term in INTERNAL + ("checks pass", "fix-1"):
        if term in text.lower():
            bad.append("agent note shown with internal term %r" % term)
    return ["agent wording: " + b for b in bad]


def check_many_projects(browser, base):
    """With a long project list, the phone summary still fits on the first screen."""
    def patch(route):
        resp = route.fetch()
        real = resp.json()
        extra = [dict(real[i % len(real)], name="project-%02d" % i) for i in range(30)]
        route.fulfill(response=resp, json=real + extra)
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.route("**/api/projects", patch)
    page.goto("%s/#p=parser" % base)
    page.wait_for_timeout(1000)
    bad = []
    glance = page.locator('[data-section="glance"]')
    if glance.count() == 0:
        bad.append("no glance summary")
    else:
        box = glance.bounding_box()
        if box["y"] + box["height"] > 845:
            bad.append("glance summary pushed below the first screen (ends at %dpx)" % (box["y"] + box["height"]))
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if overflow > 1:
        bad.append("page scrolls sideways by %dpx" % overflow)
    page.close()
    return ["35 projects on phone: " + b for b in bad]


def main():
    server.set_root(FIXTURES)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    problems = []
    pdir = os.path.join(FIXTURES, "projects")
    on_disk = {n for n in os.listdir(pdir) if not n.startswith(".") and os.path.isdir(os.path.join(pdir, n))}
    if on_disk != set(NEEDS):
        # A new fixture must say whether its situation needs the human, or it would go unchecked.
        problems += ["fixture %r is not listed in NEEDS in checks/glance.py" % n for n in sorted(on_disk - set(NEEDS))]
        problems += ["NEEDS lists %r, but there is no such fixture" % n for n in sorted(set(NEEDS) - on_disk)]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in sorted(NEEDS):
            for label, w, h in VIEWS:
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto("%s/#p=%s" % (base, name))
                page.wait_for_timeout(1000)
                problems += check_view(page, name, label, h)
                page.close()
        problems += check_agent_words(browser, base)
        problems += check_many_projects(browser, base)
        browser.close()
    httpd.shutdown()
    if problems:
        print("FAILED (%d):\n- %s" % (len(problems), "\n- ".join(problems)))
        sys.exit(1)
    print("All %d fixtures answer 'what is it doing' and 'does it need me' at a glance, "
          "with detail on demand" % len(NEEDS))


if __name__ == "__main__":
    main()
