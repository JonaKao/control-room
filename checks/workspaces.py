"""Workspaces: several framework folders, one shown at a time, through `control-room serve --config <temp>`
and the page in a headless browser.

With two copies of the fixtures (alpha: all nine projects, beta: two) and a temporary settings folder:
- first start, no workspace: a welcome screen says what a workspace is (framework, projects) and offers a
  place to add one; the switcher says there is none yet;
- a folder that is not a workspace is refused with a plain reason, and nothing is added;
- adding alpha shows its nine projects; adding beta in the settings (the gear) shows its two;
- the switcher at the top of the rail shows the current workspace's name, and picking another one shows
  its projects within one poll (2.5 s, plus a little);
- a workspace can be renamed and removed in the settings;
- after a restart (same settings folder) the list, the names and the shown workspace are the same;
- a workspace whose folder is gone stays in the list marked "not found", the core still starts, and
  showing it says the folder was not found, with its path;
- the settings say which Python was found ("Found: Python 3.x at ..."), and say so when the chosen
  Python does not start;
- the switcher and the gear fit in the rail (one row, inside it) on a wide window and at phone width,
  no JavaScript errors, no sideways scrolling.
Screenshots: plots/render-workspaces-*.png.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import app_server  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright is not installed (see checks/render.py).")
    sys.exit(1)

FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
PLOTS = os.path.join(PROJECT, "plots")
POLL_S = 2.5
problems = []


def rail_names(page):
    return sorted(page.eval_on_selector_all("#projects .proj[data-p]:not([data-workspace])", "els => els.map(e => e.dataset.p)"))


def wait_rail(page, names, within):
    """Wait until the rail lists exactly `names`; return the seconds it took, or None."""
    started = time.time()
    while time.time() - started < within:
        if rail_names(page) == sorted(names):
            return time.time() - started
        page.wait_for_timeout(100)
    return None


def switcher(page):
    return page.inner_text("#ws-switch .wsn").strip()


def open_page(browser, base, errors, w=1440, h=900):
    page = browser.new_page(viewport={"width": w, "height": h})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.goto(base)
    page.wait_for_selector("#ws-switch", timeout=15000)
    page.wait_for_timeout(1200)
    return page


def check_fit(page, label):
    """The switcher and the gear sit on one row inside the rail."""
    box = page.evaluate("""() => { const r = e => document.querySelector(e).getBoundingClientRect();
        const rail = r('.rail'), sw = r('#ws-switch'), g = r('#gear');
        return {rail: [rail.left, rail.right], sw: [sw.left, sw.right, sw.top, sw.height], gear: [g.left, g.right, g.top, g.height],
                over: document.documentElement.scrollWidth - innerWidth}; }""")
    left, right = box["rail"]
    if box["sw"][0] < left or box["gear"][1] > right + 0.5:
        problems.append("%s: switcher or gear sticks out of the rail: %r" % (label, box))
    if abs(box["sw"][2] + box["sw"][3] / 2 - box["gear"][2] - box["gear"][3] / 2) > 2:
        problems.append("%s: switcher and gear are not on one row: %r" % (label, box))
    if box["sw"][1] - box["sw"][0] < 120:
        problems.append("%s: the switcher is too narrow to read a name (%d px)" % (label, box["sw"][1] - box["sw"][0]))
    if box["over"] > 1:
        problems.append("%s: page scrolls sideways by %d px" % (label, box["over"]))


def settings_add(page, path):
    page.click("#gear")
    page.wait_for_selector("#settings[open] [data-settings=workspaces] [data-ws-add-path]")
    page.fill("#settings [data-ws-add-path]", path)
    page.click("#settings [data-ws-add-go]")
    page.wait_for_timeout(800)


def close_settings(page):
    if page.evaluate("document.querySelector('#settings').open"):
        page.click("#settings [data-settings-close]")


def menu(page, keep_open=False):
    """The switcher's list, as the person sees it after opening it; closed again unless keep_open."""
    page.click("#ws-switch")
    page.wait_for_selector("#ws-menu:not([hidden])", timeout=5000)
    items = page.eval_on_selector_all("#ws-menu [data-ws-path]", """els => els.map(e => ({name: e.querySelector('.wn').textContent,
        current: e.getAttribute('aria-checked') === 'true', missing: !!e.querySelector('[data-ws-missing]'), path: e.dataset.wsPath}))""")
    if not keep_open:
        page.keyboard.press("Escape")
        page.wait_for_selector("#ws-menu[hidden]", state="attached", timeout=5000)
    return items


def main():
    os.makedirs(PLOTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="aaf-workspaces-")
    config = os.path.join(tmp, "config")
    alpha, beta, plain = os.path.join(tmp, "alpha"), os.path.join(tmp, "beta"), os.path.join(tmp, "just-a-folder")
    shutil.copytree(FIXTURES, alpha)
    os.makedirs(os.path.join(beta, "projects"))
    for n in ("brand-new", "parser"):
        shutil.copytree(os.path.join(FIXTURES, "projects", n), os.path.join(beta, "projects", n))
    os.makedirs(os.path.join(plain, "notes"))
    all_names = sorted(os.listdir(os.path.join(alpha, "projects")))
    errors = []
    srv = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            srv = app_server.Served(None, config=config)

            # First start: no workspace.
            page = open_page(browser, srv.base, errors)
            welcome = page.query_selector("[data-ws-welcome=first]")
            text = welcome.inner_text() if welcome else ""
            for words in ("workspace", "framework", "projects"):
                if words not in text.lower():
                    problems.append("first start: the welcome screen does not explain %r: %r" % (words, text[:300]))
            if not page.query_selector("[data-ws-welcome=first] [data-ws-add-path]"):
                problems.append("first start: no way to add a workspace on the welcome screen")
            if "none" not in switcher(page).lower():
                problems.append("first start: the switcher says %r instead of that there is none yet" % switcher(page))
            check_fit(page, "first start")
            page.screenshot(path=os.path.join(PLOTS, "render-workspaces-welcome.png"))

            # A folder that is not a workspace is refused, in plain words.
            page.fill("[data-ws-add-path]", plain)
            page.click("[data-ws-add-go]")
            page.wait_for_timeout(600)
            err = page.inner_text("[data-ws-error]") if page.query_selector("[data-ws-error]:not([hidden])") else ""
            if "not a workspace" not in err or "projects" not in err:
                problems.append("refuse: no plain reason shown for a folder without projects: %r" % err)
            if app_server.get_json(srv.base, "/api/workspaces")["workspaces"]:
                problems.append("refuse: the refused folder was added anyway")

            # Add alpha from the welcome screen, then beta in the settings.
            page.fill("[data-ws-add-path]", alpha)
            page.click("[data-ws-add-go]")
            if wait_rail(page, all_names, 6) is None:
                problems.append("add: alpha's nine projects did not appear: %s" % rail_names(page))
            if switcher(page) != "alpha":
                problems.append("add: the switcher says %r, expected 'alpha'" % switcher(page))
            settings_add(page, beta)
            close_settings(page)
            if wait_rail(page, ["brand-new", "parser"], 6) is None or switcher(page) != "beta":
                problems.append("add in settings: beta is not shown (%r, %s)" % (switcher(page), rail_names(page)))

            # Switch back with the switcher: alpha's projects within one poll.
            items = menu(page, keep_open=True)
            if [i["name"] for i in items] != ["alpha", "beta"] or not items[1]["current"]:
                problems.append("switcher: the list is %r" % items)
            page.screenshot(path=os.path.join(PLOTS, "render-workspaces-switcher.png"))
            page.click('#ws-menu [data-ws-path="%s"]' % items[0]["path"].replace("\\", "\\\\"))
            took = wait_rail(page, all_names, POLL_S + 1.5)
            if took is None or took > POLL_S:
                problems.append("switch: alpha's projects took %s s (at most one poll, %.1f s)" % (took, POLL_S))
            if switcher(page) != "alpha":
                problems.append("switch: the switcher says %r after picking alpha" % switcher(page))
            if not page.query_selector("main [data-section]"):
                page.wait_for_timeout(1500)
                if not page.query_selector("main [data-section]"):
                    problems.append("switch: no project shown after switching")

            # Rename alpha and remove beta in the settings.
            page.click("#gear")
            page.wait_for_selector("#settings[open] [data-ws-row]")
            row = '#settings [data-ws-row="%s"]' % alpha.replace("\\", "\\\\")
            page.fill(row + " [data-ws-name]", "   ")
            page.click(row + " [data-ws-rename-go]")
            page.wait_for_timeout(400)
            if not page.query_selector(row + " [data-ws-error]:not([hidden])"):
                problems.append("rename: an empty name was not refused")
            page.fill(row + " [data-ws-name]", "Main workspace")
            page.click(row + " [data-ws-rename-go]")
            page.wait_for_timeout(600)
            found = page.inner_text("#settings [data-python-found]")
            if not found.startswith("Found: Python 3.") or " at " not in found:
                problems.append("settings: the Python line says %r, expected 'Found: Python 3.x at ...'" % found)
            ratio = page.evaluate("""() => {
                const rgb = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
                const lum = c => { const v = rgb(c).map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
                                   return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
                const a = lum(getComputedStyle(document.querySelector('#settings [data-python-found]')).color);
                const b = lum(getComputedStyle(document.querySelector('#settings')).backgroundColor);
                return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); }""")
            if ratio < 4.5:
                problems.append("settings: the Python line is hard to read (contrast %.1f:1 against the panel)" % ratio)
            page.screenshot(path=os.path.join(PLOTS, "render-workspaces-settings.png"))
            page.click('#settings [data-ws-row="%s"] [data-ws-remove]' % beta.replace("\\", "\\\\"))
            page.wait_for_timeout(800)
            # The Python setting: a Python that does not start is said, clearing it finds one again.
            page.fill("#settings [data-python-path]", os.path.join(tmp, "no-python.exe"))
            page.click("#settings [data-python-go]")
            page.wait_for_timeout(1500)
            said = page.inner_text("#settings [data-python-found]")
            if "did not start" not in said:
                problems.append("settings: a Python that does not start is not mentioned: %r" % said)
            page.fill("#settings [data-python-path]", "")
            page.click("#settings [data-python-go]")
            page.wait_for_timeout(1500)
            if "did not start" in page.inner_text("#settings [data-python-found]"):
                problems.append("settings: clearing the Python path did not go back to the one found")
            close_settings(page)
            page.wait_for_timeout(POLL_S * 1000)
            if switcher(page) != "Main workspace":
                problems.append("rename: the switcher says %r" % switcher(page))
            if [i["name"] for i in menu(page)] != ["Main workspace"]:
                problems.append("remove: beta is still listed")
            page.close()

            # Restart: same settings folder, same list, names and current workspace.
            srv.stop()
            srv = app_server.Served(None, config=config)
            page = open_page(browser, srv.base, errors)
            if switcher(page) != "Main workspace" or wait_rail(page, all_names, 6) is None:
                problems.append("restart: shows %r with %s" % (switcher(page), rail_names(page)))
            page.close()

            # A workspace whose folder is gone: listed as not found, the core still starts.
            app_server.get_json  # (the page adds it the way a person would)
            page = open_page(browser, srv.base, errors)
            settings_add(page, beta)
            close_settings(page)
            page.close()
            srv.stop()
            shutil.move(beta, beta + "-unplugged")
            srv = app_server.Served(None, config=config)
            page = open_page(browser, srv.base, errors)
            items = menu(page, keep_open=True)
            gone = [i for i in items if i["name"] == "beta"]
            if not gone or not gone[0]["missing"]:
                problems.append("missing folder: beta is not listed as not found: %r" % items)
            missing = page.query_selector("[data-ws-welcome=missing]")
            if not missing or beta not in missing.inner_text():
                problems.append("missing folder: showing it does not say its folder (with its path) was not found")
            if page.get_attribute("#ws-switch", "data-found") != "no":
                problems.append("missing folder: the switcher does not mark it")
            if rail_names(page):
                problems.append("missing folder: the rail still lists projects %s" % rail_names(page))
            page.screenshot(path=os.path.join(PLOTS, "render-workspaces-missing.png"))
            page.click('#ws-menu [data-ws-path="%s"]' % alpha.replace("\\", "\\\\"))
            if wait_rail(page, all_names, POLL_S + 1.5) is None:
                problems.append("missing folder: could not go back to the other workspace")
            check_fit(page, "desktop")
            page.close()
            phone = open_page(browser, srv.base, errors, 390, 844)
            check_fit(phone, "phone")
            phone.screenshot(path=os.path.join(PLOTS, "render-workspaces-phone.png"))
            phone.close()
            browser.close()
    except Exception as e:
        import traceback
        where = [l.strip() for l in traceback.format_exc().splitlines() if "workspaces.py" in l][-1:]
        problems.append("the workspaces check stopped: %s (%s)" % (str(e).splitlines()[0], "; ".join(where)))
    finally:
        if srv:
            srv.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    if errors:
        problems.append("JavaScript errors: %s" % errors[:3])
    if problems:
        print("FAIL: workspaces:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: welcome screen, refusal, add, switch within one poll, rename, remove, restart, a missing folder "
          "and the Python line all work; the switcher and gear fit the rail")
    return 0


if __name__ == "__main__":
    sys.exit(main())
