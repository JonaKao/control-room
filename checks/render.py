"""Render the page in a headless browser for every fixture project and save screenshots.

Fails on JavaScript errors, on a page that shows its "server not reachable" fallback,
or on horizontal scrolling at phone width. Screenshots land in plots/ so the agent can
open them with the Read tool and the dashboard shows them.

First-time setup (from this project folder):
  python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
"""
import os
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
PLOTS = os.path.join(PROJECT, "plots")
VIEWS = [("desktop", 1440, 900, "light"), ("desktop-dark", 1440, 900, "dark"), ("phone", 390, 844, "light")]


def main():
    server.set_root(FIXTURES)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.makedirs(PLOTS, exist_ok=True)
    projects = sorted(os.listdir(os.path.join(FIXTURES, "projects")))
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in projects:
            for label, w, h, scheme in VIEWS:
                page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                # Remote resources (web fonts) may be offline; only the page's own requests count.
                page.on("console", lambda m: errors.append(m.text)
                        if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
                page.on("requestfailed", lambda r: errors.append("failed request " + r.url)
                        if r.url.startswith(base) else None)
                page.goto("%s/#p=%s" % (base, name))
                page.wait_for_timeout(1200)
                body = page.inner_text("body")
                if "not reachable" in body:
                    problems.append("%s/%s: page shows the 'server not reachable' fallback" % (name, label))
                if errors:
                    problems.append("%s/%s: JavaScript errors: %s" % (name, label, "; ".join(errors[:3])))
                if label == "phone":
                    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                    if overflow > 1:
                        problems.append("%s/phone: page scrolls sideways by %dpx" % (name, overflow))
                page.screenshot(path=os.path.join(PLOTS, "render-%s-%s.png" % (name, label)),
                                full_page=(label != "phone"))
                page.close()
        # The workspace view ("All projects": the track record across projects).
        for label, w, h, scheme in VIEWS:
            page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
            page.goto("%s/#p=*" % base)
            page.wait_for_timeout(1200)
            if not page.query_selector('[data-section="ws-summary"]'):
                problems.append("workspace/%s: the track record across projects is not shown" % label)
            if errors:
                problems.append("workspace/%s: JavaScript errors: %s" % (label, "; ".join(errors[:3])))
            if page.evaluate("document.documentElement.scrollWidth - window.innerWidth") > 1:
                problems.append("workspace/%s: page scrolls sideways" % label)
            page.screenshot(path=os.path.join(PLOTS, "render-workspace-%s.png" % label), full_page=(label != "phone"))
            page.close()
        browser.close()
    httpd.shutdown()
    if problems:
        print("FAILED:\n- " + "\n- ".join(problems))
        sys.exit(1)
    print("Rendered %d fixture projects in %d views without errors; screenshots in plots/" % (len(projects), len(VIEWS)))


if __name__ == "__main__":
    main()
