"""Check the instrument-panel layout from design/DESIGN.md, for every fixture project.

At laptop size (1440x900), with the page scrolled to the top:
- the hero ([data-section=glance]) and the five main panels (step by step, tests, track record,
  where the time went, where the agent works) are all fully on the first screen;
- the hero spans the whole main area (or shares its row with the "what to do" card, which then
  takes the hero's right half); row 2 is step by step, tests and track record side by side in
  roughly 5 : 3 : 4 columns; row 3 is where the time went and where the agent works in 8 : 4;
- the sections come in the design's order: hero, what to do (when needed), the five panels, then
  Git, pictures and more detail below;
- the left rail shows four workspace numbers ([data-fleet]: need you, working, finished, first try)
  and a tiny picture for every project ([data-mini]).
On a phone (390x844): one column in the same order, and no sideways scrolling.
Theme: dark by default, light after the theme switch (remembered after a reload); the colour
tokens are the ones in DESIGN.md, and every phase is drawn in its token's colour in the loop
stepper, the live steps and the task timeline. Fonts: the condensed face for headings and big
numbers, the tight sans for body text, mono for times.
The first-screen rule is also checked on a temporary workspace with real Git repositories
(checks/git_workspace.py), where the change map draws real tiles and the Git section appears below.
Screenshots: plots/render-layout-*.png (compare with design/mockup-dark.png).
"""
import os
import sys
import threading
from datetime import datetime
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

FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
PLOTS = os.path.join(PROJECT, "plots")
NOW = "2026-10-14T14:50:00+02:00"
PANELS = ["live", "health", "record", "timeline", "changes"]
BELOW = ["git", "plots", "details"]
# Expected column spans on the 12-column grid.
SPANS = {"live": 5, "health": 3, "record": 4, "timeline": 8, "changes": 4}
ROWS = [["live", "health", "record"], ["timeline", "changes"]]
TOKENS = {  # DESIGN.md, dark then light
    "--plan": ("#6F7F96", "#8A97A8"), "--change": ("#5B93E6", "#2F62A8"), "--test": ("#F0A92E", "#C98510"),
    "--review": ("#A07CF0", "#7650B5"), "--polish": ("#EC6E9B", "#C04E78"), "--pass": ("#35C08E", "#18825F"),
    "--fail": ("#F0614E", "#C33B2C"), "--bg": ("#0C1320", "#E4E8EC"), "--panel": ("#121C2C", "#F7F8F9"),
    "--panel2": ("#18243A", "#EEF1F4"), "--ink": ("#E6ECF4", "#111A26"), "--muted": ("#8796AB", "#5E6B7B"),
    "--rule": ("#24324A", "#CBD3DC"),
}
PHASE_TOKEN = {"planning": "--plan", "implementing": "--change", "checking": "--test", "reviewing": "--review", "fixing": "--polish"}


def rgb(hexcode):
    h = hexcode.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def open_page(browser, base, name, w=1440, h=900, scheme="light", storage=None):
    ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
    if storage:
        ctx.add_init_script("try { %s } catch (e) {}" % "".join(
            "localStorage.setItem(%r, %r);" % kv for kv in storage.items()))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.clock.set_fixed_time(datetime.fromisoformat(NOW))
    page.goto("%s/#p=%s" % (base, name))
    page.wait_for_selector('[data-section="glance"]', timeout=15000)
    page.wait_for_timeout(900)
    return ctx, page, errors


def boxes(page):
    return page.eval_on_selector_all("main [data-section]", """els => els
        .filter(e => e.parentElement.closest('[data-section]') === null)
        .map(e => { const b = e.getBoundingClientRect();
                    return {s: e.dataset.section, x: b.left, y: b.top, w: b.width, h: b.height, r: b.right, b: b.bottom}; })""")


def check_desktop(page, name):
    bad = []
    got = boxes(page)
    by = {b["s"]: b for b in got}
    order = [b["s"] for b in got]
    want = ["glance"] + (["action"] if "action" in by else []) + PANELS
    if order[:len(want)] != want:
        return ["sections in order %s, expected %s first" % (order, want)]
    rest = [s for s in order[len(want):]]
    if [s for s in rest if s not in BELOW] or rest != [s for s in BELOW if s in rest]:
        bad.append("below the panels: %s, expected some of %s in that order" % (rest, BELOW))
    main = page.eval_on_selector("main", "m => { const b = m.getBoundingClientRect(); const cs = getComputedStyle(m);"
                                         " return {x: b.left + parseFloat(cs.paddingLeft), r: b.right - parseFloat(cs.paddingRight)}; }")
    for s in ["glance"] + (["action"] if "action" in by else []) + PANELS:
        b = by[s]
        if b["y"] < -0.5 or b["b"] > 900.5 or b["r"] > 1440.5 or b["w"] < 40:
            bad.append("%s is not fully on the first screen (top %d, bottom %d, right %d)" % (s, b["y"], b["b"], b["r"]))
    g = by["glance"]
    full = main["r"] - main["x"]
    if "action" in by:
        a = by["action"]
        if abs(a["y"] - g["y"]) > 2 or a["x"] < g["r"] or abs(a["r"] - main["r"]) > 2 or abs(g["x"] - main["x"]) > 2:
            bad.append("the 'what to do' card does not take the hero's right half (hero %s, card %s)" % (g, a))
    elif abs(g["x"] - main["x"]) > 2 or abs(g["r"] - main["r"]) > 2:
        bad.append("hero does not span the main area (%d..%d of %d..%d)" % (g["x"], g["r"], main["x"], main["r"]))
    top = max(g["b"], by["action"]["b"] if "action" in by else 0)
    prev = top
    for row in ROWS:
        ys = [by[s]["y"] for s in row]
        if max(ys) - min(ys) > 2:
            bad.append("%s are not side by side (tops %s)" % (row, [round(y) for y in ys]))
        if min(ys) < prev - 0.5:
            bad.append("%s start above the row before them" % row)
        prev = max(by[s]["b"] for s in row)
        for s in row:
            frac = by[s]["w"] / full
            if abs(frac - SPANS[s] / 12) > 0.035:
                bad.append("%s is %.2f of the width, expected about %d of 12 columns" % (s, frac, SPANS[s]))
    return bad


def check_rail(page):
    bad = []
    fleet = page.eval_on_selector_all("[data-fleet] [data-fleet-num]", "els => els.map(e => [e.dataset.fleetNum, e.textContent.trim()])")
    if [k for k, _ in fleet] != ["need", "working", "finished", "first-try"]:
        bad.append("rail numbers %s, expected need you, working, finished, first try" % fleet)
    rows = page.eval_on_selector_all("#projects .proj:not([data-workspace])", "els => els.map(e => !!e.querySelector('[data-mini] svg, svg[data-mini]'))")
    if not rows or not all(rows):
        bad.append("not every project row has its tiny picture ([data-mini]): %s" % rows)
    return bad


def check_phone(page, name):
    bad = []
    got = boxes(page)
    order = [b["s"] for b in got]
    want = ["glance"] + (["action"] if "action" in order else []) + PANELS
    if order[:len(want)] != want:
        bad.append("phone order %s, expected %s first" % (order, want))
    xs = {round(b["x"]) for b in got}
    ws = {round(b["w"]) for b in got}
    if len(xs) != 1 or len(ws) != 1:
        bad.append("phone sections are not one column (lefts %s, widths %s)" % (sorted(xs), sorted(ws)))
    ys = [b["y"] for b in got]
    if ys != sorted(ys):
        bad.append("phone sections are not stacked top to bottom")
    if page.evaluate("document.documentElement.scrollWidth - window.innerWidth") > 1:
        bad.append("phone page scrolls sideways")
    return bad


def tokens(page):
    return page.evaluate("names => { const cs = getComputedStyle(document.documentElement);"
                         " return Object.fromEntries(names.map(n => [n, cs.getPropertyValue(n).trim().toUpperCase()])); }", list(TOKENS))


def resolved(page, token):
    """A token's colour as the browser draws it."""
    return page.evaluate("t => { const d = document.createElement('i'); d.style.color = 'var(' + t + ')'; document.body.appendChild(d);"
                         " const c = getComputedStyle(d).color; d.remove(); return c; }", token)


def check_theme(browser, base):
    bad = []
    for scheme in ("light", "dark"):
        ctx, page, _ = open_page(browser, base, "image-classifier", scheme=scheme)
        if page.evaluate("getComputedStyle(document.body).backgroundColor") != rgb(TOKENS["--bg"][0]):
            bad.append("theme: not dark by default (browser prefers %s)" % scheme)
        got = tokens(page)
        for k, (dark, _) in TOKENS.items():
            if got[k] != dark.upper():
                bad.append("theme: dark %s is %r, DESIGN.md says %s" % (k, got[k], dark))
        page.click("#theme")
        page.wait_for_timeout(150)
        if page.evaluate("getComputedStyle(document.body).backgroundColor") != rgb(TOKENS["--bg"][1]):
            bad.append("theme: the switch does not turn on the light theme (browser prefers %s)" % scheme)
        got = tokens(page)
        for k, (_, light) in TOKENS.items():
            if got[k] != light.upper():
                bad.append("theme: light %s is %r, DESIGN.md says %s" % (k, got[k], light))
        page.reload()
        page.wait_for_selector('[data-section="glance"]')
        if page.evaluate("getComputedStyle(document.body).backgroundColor") != rgb(TOKENS["--bg"][1]):
            bad.append("theme: the light choice is not remembered after a reload")
        ctx.close()
    return bad


def check_colours(browser, base):
    """One colour per phase, the same in the loop stepper, the live steps and the timeline."""
    bad = []
    for theme in ("dark", "light"):
        ctx, page, _ = open_page(browser, base, "image-classifier", storage={"aaf.theme": theme})
        want = {p: resolved(page, t) for p, t in PHASE_TOKEN.items()}
        segs = page.eval_on_selector_all("[data-seg]", "els => els.map(e => [e.dataset.phase, getComputedStyle(e).backgroundColor])")
        for ph, bg in segs:
            if ph in want and bg != want[ph]:
                bad.append("%s: timeline draws %s in %s, not its token %s" % (theme, ph, bg, want[ph]))
        node = page.eval_on_selector('[data-viz="loop"] [aria-current="step"] .node', "e => getComputedStyle(e).backgroundColor")
        if node != want["checking"]:
            bad.append("%s: the loop stepper draws the current stage (testing) in %s, not %s" % (theme, node, want["checking"]))
        kinds = {"edit": "implementing", "test": "checking", "read": "planning", "search": "planning"}
        steps = page.eval_on_selector_all("[data-section=live] [data-kind]", "els => els.map(e => [e.dataset.kind, getComputedStyle(e.querySelector('.kicon')).backgroundColor])")
        seen = set()
        for kind, bg in steps:
            if kind in kinds:
                seen.add(kind)
                if bg != want[kinds[kind]]:
                    bad.append("%s: a %r step's icon is %s, not the %s colour %s" % (theme, kind, bg, kinds[kind], want[kinds[kind]]))
        if not seen:
            bad.append("%s: no live step of a phase kind to compare colours with" % theme)
        ctx.close()
    ctx, page, _ = open_page(browser, base, "example-done")
    rev = page.eval_on_selector_all("[data-section=live] [data-subagent=reviewer] .kicon", "els => els.map(e => getComputedStyle(e).backgroundColor)")
    want = resolved(page, "--review")
    if not rev or any(c != want for c in rev):
        bad.append("reviewer steps are not drawn in the review colour %s: %s" % (want, rev))
    ctx.close()
    return bad


def check_fonts(browser, base):
    bad = []
    ctx, page, _ = open_page(browser, base, "image-classifier")
    fam = page.evaluate("""() => {
        const f = s => { const e = document.querySelector(s); return e ? getComputedStyle(e).fontFamily : ''; };
        return {head: f('[data-section=glance] [data-doing]'), label: f('[data-section=live] .ph h3'),
                body: f('body'), time: f('[data-section=live] .step-list .t')}; }""")
    for k, face in (("head", "IBM Plex Sans Condensed"), ("label", "IBM Plex Sans Condensed"), ("body", "Inter Tight"), ("time", "JetBrains Mono")):
        if not fam[k].strip('"\'').startswith(face):
            bad.append("fonts: %s uses %r, expected %s first" % (k, fam[k], face))
    ctx.close()
    return bad


def check_git(browser):
    """With real repositories: the treemap preview and the hero still fit, and Git sits below the panels."""
    bad = []
    root, _ = gw.make_workspace()
    gw.code_repo(root, "scheduler")
    server.set_root(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        for name in ("scheduler", "example-done", "parser"):
            ctx, page, errors = open_page(browser, base, name)
            page.wait_for_selector('[data-section="changes"] [data-map-ready]', timeout=20000)
            page.wait_for_selector('[data-section="git"] [data-git-ready]', timeout=20000)
            page.wait_for_timeout(300)
            if name == "scheduler" and not page.query_selector('[data-section="changes"] [data-tile]'):
                bad.append("git/%s: the change map draws no tiles" % name)
            if name == "scheduler":
                page.screenshot(path=os.path.join(PLOTS, "render-layout-git-desktop-dark.png"))
            bad += ["git/%s: %s" % (name, b) for b in check_desktop(page, name)]
            if "git" not in [b["s"] for b in boxes(page)]:
                bad.append("git/%s: no Git section below the panels" % name)
            bad += ["git/%s: JavaScript error: %s" % (name, e) for e in errors[:3]]
            ctx.close()
    finally:
        httpd.shutdown()
        gw.remove_workspace(root)
    return bad


def main():
    server.set_root(FIXTURES)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.makedirs(PLOTS, exist_ok=True)
    names = sorted(n for n in os.listdir(os.path.join(FIXTURES, "projects")) if not n.startswith("."))
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in names:
            ctx, page, errors = open_page(browser, base, name)
            problems += ["%s/desktop: %s" % (name, b) for b in check_desktop(page, name)]
            if name == names[0]:
                problems += ["rail: " + b for b in check_rail(page)]
            if name == "image-classifier":
                page.screenshot(path=os.path.join(PLOTS, "render-layout-desktop-dark.png"))
            problems += ["%s: JavaScript error: %s" % (name, e) for e in errors[:3]]
            ctx.close()
            ctx, page, _ = open_page(browser, base, name, w=390, h=844)
            problems += ["%s/phone: %s" % (name, b) for b in check_phone(page, name)]
            ctx.close()
        ctx, page, _ = open_page(browser, base, "image-classifier", storage={"aaf.theme": "light"})
        page.screenshot(path=os.path.join(PLOTS, "render-layout-desktop-light.png"))
        ctx.close()
        problems += check_theme(browser, base)
        problems += check_colours(browser, base)
        problems += check_fonts(browser, base)
        httpd.shutdown()
        problems += check_git(browser)
        browser.close()
    if problems:
        print("Layout check FAILED (%d):" % len(problems))
        for pr in problems:
            print("  - " + pr)
        sys.exit(1)
    print("Layout check passed for %d fixtures: hero and five panels on the first 1440x900 screen, design order, "
          "one column on phones, dark by default, DESIGN.md colours and fonts" % len(names))


if __name__ == "__main__":
    main()
