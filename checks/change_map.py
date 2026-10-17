"""Check the change map ("Where the agent works") on a temporary workspace with real repositories.

The data comes from `framework/aaf.py git files <project>`. checks/git_workspace.py builds the
workspace; code_repo() turns the `scheduler` fixture into a repository with a small code tree whose
files changed unevenly. In a headless browser it checks:
- the section ([data-section=changes]) follows the task timeline, as in design/DESIGN.md;
- one tile per file ([data-tile]), grouped by top-level folder ([data-group]), tiles inside their
  group, no overlaps, everything inside the map;
- tile area follows file size; colour follows how often commits changed the file (more changes,
  darker, in light mode), with a legend;
- the agent's bookkeeping (state/, plots/) is hidden by default and one tap shows it; the choice
  is remembered after a reload;
- tapping a tile shows its path, how many times it changed and its last change; tapping again closes;
- a project without Git (brand-new) and a workspace without the framework tool show clear empty
  states;
- plain words outside the tiles, no sideways scrolling at phone width, no JavaScript errors.
Screenshots: plots/render-map-*.png.
"""
import json
import os
import re
import statistics
import subprocess
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
FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
BOOKKEEPING = ("state/", "plots/")
INTERNAL = re.compile(r"\b(iteration|implementing|phase)\b|\baaf\b|\b[\w-]+\.(jsonl?|md)\b|\bstate/|\bplots/", re.I)


def aaf_files(root, name):
    out = subprocess.run([sys.executable, os.path.join(root, "framework", "aaf.py"), "git", "files", name],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["files"]


def open_page(browser, base, name, w=1440, h=900, scheme="light", storage=None):
    ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
    if scheme == "light":  # dark is the page's default; light is the choice the theme switch stores
        ctx.add_init_script("try { localStorage.setItem('aaf.theme', 'light'); } catch (e) {}")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.goto("%s/#p=%s" % (base, name))
    page.wait_for_selector('[data-section="changes"] [data-map-ready]', timeout=20000)
    page.wait_for_timeout(200)
    return page, errors


def tiles(page):
    return page.eval_on_selector_all("[data-tile]", """els => els.map(e => { const b = e.getBoundingClientRect();
        const g = e.closest('[data-group]'), gb = g ? g.getBoundingClientRect() : null;
        return {path: e.dataset.path, commits: +e.dataset.commits, bytes: +e.dataset.bytes,
                x: b.left, y: b.top, w: b.width, h: b.height, bg: getComputedStyle(e).backgroundColor,
                group: g ? g.dataset.folder : null, gx: gb && gb.left, gy: gb && gb.top, gw: gb && gb.width, gh: gb && gb.height}; })""")


def lum(rgb):
    nums = [float(x) for x in re.findall(r"[\d.]+", rgb.split("(", 1)[1])[:3]]
    r, g, b = nums if rgb.startswith("color(") else [x / 255 for x in nums]  # color(srgb 0..1) or rgb(0..255)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def folder(path):
    return path.split("/", 1)[0] if "/" in path else ""


def check_map(page, label, files):
    bad = []
    got = tiles(page)
    if sorted(t["path"] for t in got) != sorted(f["path"] for f in files):
        bad.append("%s: tiles %s, expected %s" % (label, sorted(t["path"] for t in got), sorted(f["path"] for f in files)))
        return bad
    box = page.eval_on_selector("[data-map]", "e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; }")
    by = {f["path"]: f for f in files}
    for t in got:
        if t["commits"] != by[t["path"]]["commits"] or t["bytes"] != by[t["path"]]["bytes"]:
            bad.append("%s: %s carries wrong numbers" % (label, t["path"]))
        if t["group"] != folder(t["path"]):
            bad.append("%s: %s is in group %r, expected %r" % (label, t["path"], t["group"], folder(t["path"])))
        if t["gx"] is not None and (t["x"] < t["gx"] - 0.5 or t["y"] < t["gy"] - 0.5 or
                                    t["x"] + t["w"] > t["gx"] + t["gw"] + 0.5 or t["y"] + t["h"] > t["gy"] + t["gh"] + 0.5):
            bad.append("%s: %s sticks out of its group" % (label, t["path"]))
        if t["x"] < box[0] - 0.5 or t["y"] < box[1] - 0.5 or t["x"] + t["w"] > box[2] + 0.5 or t["y"] + t["h"] > box[3] + 0.5:
            bad.append("%s: %s sticks out of the map" % (label, t["path"]))
        if t["w"] < 4 or t["h"] < 4:
            bad.append("%s: %s is too small to tap (%.0fx%.0f)" % (label, t["path"], t["w"], t["h"]))
    for i, a in enumerate(got):
        for b in got[i + 1:]:
            ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if ox > 0.5 and oy > 0.5:
                bad.append("%s: %s overlaps %s" % (label, a["path"], b["path"]))
    # Area follows size, for tiles big enough that gaps and the minimum size do not matter.
    big = [t for t in got if t["w"] * t["h"] >= 2500]
    if len(big) >= 3:
        ratios = [t["w"] * t["h"] / t["bytes"] for t in big]
        med = statistics.median(ratios)
        for t, r in zip(big, ratios):
            if not 0.75 * med <= r <= 1.33 * med:
                bad.append("%s: %s area is off its size (%.2f vs %.2f px per byte)" % (label, t["path"], r, med))
    # Colour follows change count: same count, same colour; more changes, darker (light mode).
    shades = {}
    for t in got:
        shades.setdefault(t["commits"], set()).add(t["bg"])
    if any(len(v) != 1 for v in shades.values()):
        bad.append("%s: files with the same number of changes have different colours" % label)
    levels = sorted(shades)
    if len({next(iter(shades[c])) for c in levels}) < min(4, len(levels)):
        bad.append("%s: too few colour steps for %s changes" % (label, levels))
    lums = [lum(next(iter(shades[c]))) for c in levels]
    if any(b > a + 0.005 for a, b in zip(lums, lums[1:])):
        bad.append("%s: more changes is not darker (%s)" % (label, list(zip(levels, [round(x, 3) for x in lums]))))
    if not page.query_selector("[data-map-legend]"):
        bad.append("%s: no colour legend" % label)
    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if over > 1:
        bad.append("%s: page scrolls sideways by %d px" % (label, over))
    return bad


def check_scheduler(browser, base, root, want):
    bad = []
    files = aaf_files(root, "scheduler")
    code = [f for f in files if not f["path"].startswith(BOOKKEEPING)]
    if len(code) == len(files):
        return ["scheduler: test repo has no bookkeeping files to hide"]
    for label, w, h in (("desktop", 1440, 900), ("phone", 390, 844)):
        page, errors = open_page(browser, base, "scheduler", w, h)
        order = page.eval_on_selector_all("main [data-section]", "els => els.filter(e => e.parentElement.closest('[data-section]') === null)"
                                          ".map(e => e.dataset.section)")
        if "changes" not in order or "timeline" not in order or order.index("changes") != order.index("timeline") + 1:
            bad.append("scheduler/%s: change map does not follow the task timeline (%s)" % (label, order))
        bad += check_map(page, "scheduler/%s (bookkeeping hidden)" % label, code)
        words = page.eval_on_selector('[data-section="changes"]', "s => [...s.querySelectorAll('[data-map-legend],[data-map-toggle],[data-map-intro]')]"
                                      ".map(e => e.textContent).join(' ')")
        if INTERNAL.search(words):
            bad.append("scheduler/%s: internal term %r outside the tiles" % (label, INTERNAL.search(words).group(0)))
        page.locator('[data-section="changes"]').first.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(PLOTS, "render-map-%s.png" % label))
        # Tap a tile: its last change and how often it changed.
        page.click('[data-tile][data-path="scheduler/core.py"]')
        page.wait_for_timeout(200)
        det = page.query_selector("[data-file-detail]")
        text = det.inner_text() if det else ""
        n, subject = want["scheduler/core.py"]
        for part in ("scheduler/core.py", "%d " % n, subject):
            if part not in text:
                bad.append("scheduler/%s: tile detail misses %r: %r" % (label, part, text[:200]))
        if not re.search(r"\b(ago|just now|\d{1,2}:\d{2}|[A-Z][a-z]{2})\b", text):
            bad.append("scheduler/%s: tile detail has no date: %r" % (label, text[:200]))
        if page.get_attribute('[data-tile][data-path="scheduler/core.py"]', "aria-pressed") != "true":
            bad.append("scheduler/%s: tapped tile not marked" % label)
        if label == "desktop":
            page.screenshot(path=os.path.join(PLOTS, "render-map-detail.png"))
        page.click('[data-tile][data-path="scheduler/core.py"]')
        page.wait_for_timeout(200)
        if page.query_selector("[data-file-detail]"):
            bad.append("scheduler/%s: tapping the tile again does not close the detail" % label)
        # Show the bookkeeping: every file appears; the choice survives a reload.
        page.click("[data-map-toggle]")
        page.wait_for_timeout(300)
        bad += check_map(page, "scheduler/%s (everything shown)" % label, files)
        page.reload()
        page.wait_for_selector('[data-section="changes"] [data-map-ready]', timeout=20000)
        page.wait_for_timeout(200)
        if len(tiles(page)) != len(files):
            bad.append("scheduler/%s: 'show everything' not remembered after a reload" % label)
        page.click("[data-map-toggle]")
        page.wait_for_timeout(300)
        if len(tiles(page)) != len(code):
            bad.append("scheduler/%s: hiding the bookkeeping again does not work" % label)
        if errors:
            bad.append("scheduler/%s: JavaScript errors: %s" % (label, errors[:3]))
        page.context.close()
    # Dark mode: still one colour per step and a screenshot.
    page, errors = open_page(browser, base, "scheduler", scheme="dark")
    page.locator('[data-section="changes"]').first.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    page.screenshot(path=os.path.join(PLOTS, "render-map-desktop-dark.png"))
    if errors:
        bad.append("scheduler/dark: JavaScript errors: %s" % errors[:3])
    page.context.close()
    return bad


def check_keyboard(browser, base):
    """Keyboard: Enter on a tile opens its detail and focus stays on it, so Enter closes it again.
    The page must not move (scheduler has a Git section above and pictures below the map)."""
    bad = []
    page, errors = open_page(browser, base, "scheduler")
    sel = '[data-tile][data-path="scheduler/queue.py"]'
    page.locator(sel).scroll_into_view_if_needed()
    page.focus(sel)
    y = page.evaluate("window.scrollY")
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    if not page.query_selector("[data-file-detail]"):
        bad.append("keyboard: Enter on a tile does not open its detail")
    if page.evaluate("(document.activeElement && document.activeElement.dataset.path) || ''") != "scheduler/queue.py":
        bad.append("keyboard: focus left the tile after opening its detail")
    if abs(page.evaluate("window.scrollY") - y) > 2:
        bad.append("keyboard: the page moved from %d to %d px" % (y, page.evaluate("window.scrollY")))
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    if page.query_selector("[data-file-detail]"):
        bad.append("keyboard: a second Enter does not close the detail")
    if errors:
        bad.append("keyboard: JavaScript errors: %s" % errors[:3])
    page.context.close()
    return bad


def check_odd_data(browser, base):
    """A failed read is not reported as 'no Git'; a file with no counted change has a legend entry."""
    bad = []
    for body, label in (({"available": True, "repo": False, "files": [], "error": "git log timed out"}, "error"),
                        ({"available": True, "repo": True, "files": [
                            {"path": "old.py", "bytes": 4000, "commits": 0, "lines_changed": 0, "last_changed": None, "last_subject": None},
                            {"path": "new.py", "bytes": 3000, "commits": 2, "lines_changed": 9,
                             "last_changed": "2026-10-14T10:00:00+02:00", "last_subject": "Add new.py"}]}, "zero")):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.route("**/api/files?name=scheduler*", (lambda b: lambda route, *_: route.fulfill(json=b))(body))
        page.goto("%s/#p=scheduler" % base)
        page.wait_for_selector('[data-section="changes"] [data-map-ready]', timeout=20000)
        text = page.inner_text('[data-section="changes"]')
        if label == "error":
            if "not saved with Git" in text or "could not be read" not in text:
                bad.append("odd data: a failed read is shown as %r" % text[:160])
        else:
            cls = page.get_attribute('[data-tile][data-path="old.py"]', "class") or ""
            step = re.search(r"\bs(\d)\b", cls)
            legend = page.eval_on_selector_all("[data-map-legend] i", "els => els.map(e => e.className)")
            if not step or ("s" + step.group(1)) not in legend:
                bad.append("odd data: a file with no counted change has no legend colour (%r, legend %s)" % (cls, legend))
        ctx.close()
    return bad


def check_empty(browser, base, name, needle, label):
    page, errors = open_page(browser, base, name)
    bad = []
    el = page.query_selector('[data-section="changes"] [data-empty]')
    text = el.inner_text() if el else ""
    if needle not in text:
        bad.append("%s: empty state should mention %r, got %r" % (label, needle, text[:160]))
    if page.query_selector("[data-tile]"):
        bad.append("%s: tiles shown in the empty state" % label)
    if errors:
        bad.append("%s: JavaScript errors: %s" % (label, errors[:3]))
    page.context.close()
    return bad


def serve(root):
    server.set_root(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def main():
    os.makedirs(PLOTS, exist_ok=True)
    root, _ = gw.make_workspace()
    want = gw.code_repo(root, "scheduler")
    problems = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            httpd, base = serve(root)
            problems += check_scheduler(browser, base, root, want)
            problems += check_odd_data(browser, base)
            problems += check_keyboard(browser, base)
            problems += check_empty(browser, base, "brand-new", "Git", "brand-new (no repository)")
            httpd.shutdown()
            # A workspace without the framework tool (the plain fixtures).
            httpd, base = serve(FIXTURES)
            problems += check_empty(browser, base, "example-done", "not available", "fixtures without the framework tool")
            httpd.shutdown()
            browser.close()
    finally:
        gw.remove_workspace(root)
    if problems:
        print("Change map check FAILED:")
        for pr in problems:
            print("  - " + pr)
        sys.exit(1)
    print("Change map check passed; screenshots in plots/render-map-*.png")


if __name__ == "__main__":
    main()
