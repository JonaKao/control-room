"""Check the Git section of the page against real temporary repositories.

Builds a throwaway workspace (checks/git_workspace.py), serves it, and checks in a
headless browser that, per project:
- the commit timeline shows one point per commit, oldest left, coloured by its
  Checks/Review trailers ([data-state] = ok | tested | bad | none), commits not yet on
  GitHub marked ([data-pushed=no]), and subject plus decisions shown when a point is picked;
- the sync picture states ahead / behind / uncommitted files, with the file list on demand;
- the repo link appears when there is a GitHub address;
- Push sends commits and Pull fetches them, Pull is disabled while the agent works,
  and a project without Git says so without buttons;
- no JavaScript errors and no sideways scrolling on a phone.
Screenshots: plots/render-git-*.png.
"""
import os
import sys
import threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)
sys.path.insert(0, HERE)
import server  # noqa: E402
import git_workspace as gw  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright is not installed. From projects/control-room run:\n"
          "  python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium")
    sys.exit(1)

PLOTS = os.path.join(PROJECT, "plots")
# Expected colour per commit, oldest first (see gw.HISTORY).
STATES = ["none", "ok", "bad", "tested", "ok"]
WEB = "https://github.com/test/example-done"


def open_page(browser, base, name, w=1440, h=900, web=None):
    page = browser.new_page(viewport={"width": w, "height": h})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    if web:
        def patch(route):
            resp = route.fetch()
            d = resp.json()
            d["web"] = web
            route.fulfill(response=resp, json=d)
        page.route("**/api/git?name=%s*" % name, patch)
    page.goto("%s/#p=%s" % (base, name))
    page.wait_for_selector('[data-section="git"] [data-git-ready]', timeout=20000)
    return page, errors


def attr(page, sel, name):
    loc = page.locator(sel)
    return loc.first.get_attribute(name) if loc.count() else None


def check_timeline(page, label):
    bad = []
    pts = page.locator('[data-viz="git-timeline"] [data-commit]')
    states = [pts.nth(i).get_attribute("data-state") for i in range(pts.count())]
    if states != STATES:
        bad.append("%s: timeline colours %s, expected %s (oldest first)" % (label, states, STATES))
    pushed = [pts.nth(i).get_attribute("data-pushed") for i in range(pts.count())]
    if pushed[-2:] != ["no", "no"] or "no" in pushed[:-2]:
        bad.append("%s: commits not on GitHub should be the newest 2, got %s" % (label, pushed))
    if page.locator("[data-commit-detail]").count() and page.locator("[data-commit-detail]").first.is_visible() \
            and "lexer" in page.locator("[data-commit-detail]").first.inner_text():
        bad.append("%s: an old commit's decisions are shown before anything is picked" % label)
    if pts.count() >= 2:
        pts.nth(1).click()
        page.wait_for_timeout(150)
        text = page.locator("[data-commit-detail]").first.inner_text() if page.locator("[data-commit-detail]").count() else ""
        for want in ("Add the parser", "hand-written lexer", "2 of 2"):
            if want not in text:
                bad.append("%s: picking a commit does not show %r" % (label, want))
        big = page.eval_on_selector_all("[data-commit-detail] svg",
                                        "els => Math.max(0, ...els.map(e => e.getBoundingClientRect().height))")
        if big > 24:
            bad.append("%s: icons in the commit detail are %dpx tall (at most 24)" % (label, big))
    tl = page.locator('[data-viz="git-timeline"]')
    if tl.count() and pts.count():
        line_w = tl.first.bounding_box()["width"]
        span = pts.last.bounding_box()["x"] + pts.last.bounding_box()["width"] - pts.first.bounding_box()["x"]
        if line_w > span + 40:
            bad.append("%s: timeline line runs %dpx past the last commit" % (label, line_w - span))
    return bad


def check_sync(page, label, ahead, behind, changed):
    bad = []
    got = (attr(page, '[data-viz="git-sync"]', "data-ahead"), attr(page, '[data-viz="git-sync"]', "data-behind"),
           attr(page, '[data-viz="git-sync"]', "data-changed"))
    if got != (str(ahead), str(behind), str(changed)):
        bad.append("%s: sync picture says ahead/behind/changed %s, expected %s" % (label, got, (ahead, behind, changed)))
    return bad


def main():
    root, expect = gw.make_workspace()
    server.set_root(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.makedirs(PLOTS, exist_ok=True)
    problems = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()

            # Reading: example-done (2 commits not on GitHub), desktop and phone.
            for label, w, h in (("desktop", 1440, 900), ("phone", 390, 844)):
                page, errors = open_page(browser, base, "example-done", w, h, web=WEB)
                problems += check_timeline(page, "example-done/" + label)
                problems += check_sync(page, "example-done/" + label, 2, 0, 0)
                if page.locator('[data-section="git"] a[href="%s"]' % WEB).count() == 0:
                    problems.append("example-done/%s: no link to the repo on GitHub" % label)
                if label == "phone":
                    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                    if over > 1:
                        problems.append("example-done/phone: page scrolls sideways by %dpx" % over)
                if label == "phone":
                    page.locator('[data-section="git"]').first.scroll_into_view_if_needed()
                page.screenshot(path=os.path.join(PLOTS, "render-git-example-done-%s.png" % label),
                                full_page=(label == "desktop"))
                problems += ["example-done/%s: JavaScript error: %s" % (label, e) for e in errors[:3]]
                page.close()

            # No GitHub address: no link, nothing broken.
            page, errors = open_page(browser, base, "example-done")
            if page.locator('[data-section="git"] a[href^="https://github.com"]').count():
                problems.append("example-done: shows a GitHub link although the project has no GitHub address")
            # Push.
            btn = page.locator('[data-git-action="push"]')
            if btn.count() == 0 or btn.first.is_disabled():
                problems.append("example-done: Push button missing or disabled with 2 commits to send")
            else:
                btn.first.click()
                page.wait_for_function("document.querySelector('[data-viz=\"git-sync\"]')?.dataset.ahead === '0'",
                                       timeout=30000)
                if "Tidy up after review" not in gw.git(os.path.join(root, "remotes", "example-done.git"),
                                                        "log", "--format=%s", "main"):
                    problems.append("example-done: Push did not reach the remote")
                if page.locator("[data-git-message]").count() == 0 or \
                        not page.locator("[data-git-message]").first.inner_text().strip():
                    problems.append("example-done: no message after Push")
            problems += ["example-done/push: JavaScript error: %s" % e for e in errors[:3]]
            page.close()

            # parser: behind 1, one uncommitted file; Pull allowed (agent is waiting for a decision).
            page, errors = open_page(browser, base, "parser", 390, 844)
            problems += check_sync(page, "parser", 0, 1, 1)
            files = page.locator('[data-section="git"] details[data-detail="git-files"]')
            if files.count() == 0:
                problems.append("parser: uncommitted files are not listed on demand")
            elif files.first.get_attribute("open") is not None:
                problems.append("parser: the uncommitted file list is open on load")
            else:
                files.first.locator("summary").click()
                if "notes.txt" not in files.first.inner_text():
                    problems.append("parser: uncommitted file list does not name notes.txt")
            page.screenshot(path=os.path.join(PLOTS, "render-git-parser-phone.png"))
            pull = page.locator('[data-git-action="pull"]')
            if pull.count() == 0 or pull.first.is_disabled():
                problems.append("parser: Pull button missing or disabled although the agent is not working")
            else:
                pull.first.click()
                try:
                    page.wait_for_function("document.querySelector('[data-viz=\"git-sync\"]')?.dataset.behind === '0'",
                                           timeout=30000)
                except Exception:
                    problems.append("parser: Pull did not bring the newer commit")
            problems += ["parser: JavaScript error: %s" % e for e in errors[:3]]
            page.close()

            # image-classifier: agent is working, so Pull is disabled and says why.
            page, errors = open_page(browser, base, "image-classifier")
            pull = page.locator('[data-git-action="pull"]')
            if pull.count() == 0:
                problems.append("image-classifier: no Pull button")
            elif not pull.first.is_disabled():
                problems.append("image-classifier: Pull is enabled while the agent is working")
            elif "working" not in page.locator('[data-section="git"]').inner_text().lower():
                problems.append("image-classifier: does not say Pull waits until the agent stops working")
            page.close()

            # brand-new: not a Git repository.
            page, errors = open_page(browser, base, "brand-new")
            sec = page.locator('[data-section="git"]')
            if page.locator('[data-git-action]').count():
                problems.append("brand-new: shows Push/Pull although it has no Git repository")
            if "not" not in sec.inner_text().lower():
                problems.append("brand-new: does not say the project is not saved with Git")
            problems += ["brand-new: JavaScript error: %s" % e for e in errors[:3]]
            page.close()
            browser.close()
    except Exception as e:  # a timeout waiting for the section counts as a failure, not a crash
        problems.append("page did not get through the Git checks: %s" % str(e).splitlines()[0])
    finally:
        httpd.shutdown()
        gw.remove_workspace(root)
    if problems:
        print("FAILED (%d):\n- %s" % (len(problems), "\n- ".join(problems)))
        sys.exit(1)
    print("Git section: timeline, sync state, repo link, Push and Pull work for every situation")


if __name__ == "__main__":
    main()
