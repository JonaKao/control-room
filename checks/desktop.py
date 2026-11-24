"""Desktop window: the real app window (Windows, WebView2), driven over the Chrome DevTools Protocol.

Starts the built app (`control-room --root <workspace> --config <temporary folder>`) with WebView2's
remote debugging turned on (WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=N), then
connects Playwright with connect_over_cdp, so what is checked is the window itself:
- one top-level window of the app's own process, titled "Agent Control Room", showing the page from the
  app's own protocol (http://app.localhost/), with no browser frame: the page fills the window's whole
  client area (no address bar, tabs or menu), and it is at least 1280 x 800 the first time;
- the app's process listens on no TCP port (netstat; the method is first shown to see `serve`'s port);
- the rail lists all nine fixture projects and each one opens without JavaScript errors;
- Push and Pull reach the core through the window (temporary Git workspace, checks/git_workspace.py):
  the Push button sends the commits, Pull brings the newer one, Pull is refused (409) while the agent
  works, and a write without the page's header is refused (403);
- the theme and colour-blind choices, and the window's size and position, survive closing and
  restarting the app.
Screenshots: plots/render-desktop-*.png.
"""
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import app_server  # noqa: E402
import git_workspace as gw  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright is not installed (see checks/render.py).")
    sys.exit(1)

FIXTURES = os.path.join(PROJECT, "fixtures", "workspace")
PLOTS = os.path.join(PROJECT, "plots")
TITLE = "Agent Control Room"
NAMES = sorted(n for n in os.listdir(os.path.join(FIXTURES, "projects")) if not n.startswith("."))
problems = []

user32 = ctypes.windll.user32 if os.name == "nt" else None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def windows_of(pid):
    """Visible top-level windows of a process: (hwnd, title, class name, window rect, client size)."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            r, c = wintypes.RECT(), wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            user32.GetClientRect(hwnd, ctypes.byref(c))
            found.append((hwnd, title.value, cls.value, (r.left, r.top, r.right, r.bottom), (c.right, c.bottom)))
        return True
    user32.EnumWindows(each, 0)
    return found


def listening_ports(pid):
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace").stdout
    ports = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" and parts[4] == str(pid):
            ports.append(parts[1])
    return ports


class App:
    """The running app, its window and its page over CDP."""

    def __init__(self, pw, root, config):
        self.port = free_port()
        env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=%d" % self.port)
        self.proc = subprocess.Popen([app_server.EXE, "--root", root, "--config", config], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 40
        while True:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % self.port, timeout=2) as r:
                    targets = [t for t in json.loads(r.read()) if t.get("type") == "page"]
                if targets and targets[0]["url"].startswith("http"):
                    break
            except OSError:
                pass
            if time.time() > deadline or self.proc.poll() is not None:
                self.close()
                raise RuntimeError("the app window did not come up (exit code %s)" % self.proc.poll())
            time.sleep(0.3)
        self.targets = targets
        self.browser = pw.chromium.connect_over_cdp("http://127.0.0.1:%d" % self.port)
        self.page = self.browser.contexts[0].pages[0]
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text)
                     if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
        self.page.wait_for_selector("#projects .proj", timeout=20000)
        try:  # the first project's detail, not just the rail
            self.page.wait_for_selector("main [data-section]", timeout=30000)
        except Exception:
            problems.append("the window showed the project list but no project in 30 s")
        self.page.wait_for_timeout(500)
        deadline = time.time() + 10
        while not self.windows() and time.time() < deadline:
            time.sleep(0.2)

    def windows(self):
        return [w for w in windows_of(self.proc.pid) if w[1]]

    def open(self, name):
        """Open a project the way a person does: click it in the rail."""
        self.page.click('#projects .proj[data-p="%s"]' % name)
        self.page.wait_for_function("n => (document.querySelector('#projects .proj[aria-current=\"true\"]') || {}).dataset?.p === n",
                                    arg=name, timeout=15000)
        self.page.wait_for_timeout(800)

    def current(self):
        return self.page.evaluate("(document.querySelector('#projects .proj[aria-current=\"true\"]') || {dataset: {}}).dataset.p")

    def close(self, gracefully=True):
        """Close the window like a person would (WM_CLOSE), so the app saves its state; kill if it hangs."""
        if self.proc.poll() is None and gracefully:
            for w in self.windows():  # only the app's window; Tao's hidden event window must stay
                user32.PostMessageW(w[0], 0x0010, 0, 0)  # WM_CLOSE
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                problems.append("the app did not end within 15 s of closing its window")
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        try:
            self.browser.close()
        except Exception:
            pass


def check_window(app):
    wins = app.windows()
    if len(wins) != 1:
        problems.append("expected one window of the app's own process, found %r" % [(w[1], w[2]) for w in wins])
        return
    hwnd, title, cls, rect, client = wins[0]
    if title != TITLE:
        problems.append("window title %r, expected %r" % (title, TITLE))
    if len(app.targets) != 1 or not re.match(r"^https?://app\.localhost/", app.targets[0]["url"]):
        problems.append("the window shows %r, expected the app's own page (http://app.localhost/)"
                        % [t["url"] for t in app.targets])
    inner = app.page.evaluate("[innerWidth, innerHeight, devicePixelRatio]")
    if abs(inner[0] * inner[2] - client[0]) > 2 or abs(inner[1] * inner[2] - client[1]) > 2:
        problems.append("the page does not fill the window (browser parts around it?): page %r x %s, client %r"
                        % (inner[:2], inner[2], client))
    if inner[0] < 1280 or inner[1] < 800:
        problems.append("first start: window shows %d x %d, expected at least 1280 x 800" % (inner[0], inner[1]))
    ports = listening_ports(app.proc.pid)
    if ports:
        problems.append("the app listens on TCP %s; it must open no network port" % ports)


def check_netstat_sees_serve():
    """The port test is only worth something if it would see a port: `serve` must show up."""
    s = app_server.Served(FIXTURES)
    try:
        if not listening_ports(s.proc.pid):
            problems.append("netstat did not show the listening port of control-room serve: the no-port test proves nothing")
    finally:
        s.stop()


def check_fixtures(app):
    rail = app.page.eval_on_selector_all("#projects .proj[data-p]:not([data-workspace])", "els => els.map(e => e.dataset.p)")
    if sorted(rail) != NAMES:
        problems.append("rail lists %s, expected the nine fixtures %s" % (rail, NAMES))
    for name in NAMES:
        app.errors.clear()
        app.open(name)
        if app.page.evaluate("document.body.innerText").find("not reachable") >= 0:
            problems.append("%s: the window shows the 'not reachable' fallback" % name)
        if app.current() != name or name not in app.page.inner_text("main"):
            problems.append("%s: did not open (the window shows %r)" % (name, app.current()))
        if app.errors:
            problems.append("%s: JavaScript errors in the window: %s" % (name, app.errors[:3]))
        if name in ("web-scraper", "image-classifier"):
            app.page.screenshot(path=os.path.join(PLOTS, "render-desktop-%s.png" % name))


def post(app, action, name, header=True):
    return app.page.evaluate("""async ([a, n, h]) => {
        const headers = {"Content-Type": "application/json"};
        if (h) headers["X-AAF-Request"] = "control-room";
        const r = await fetch("/api/git/" + a, {method: "POST", headers, body: JSON.stringify({name: n})});
        return [r.status, await r.json().catch(() => null)]; }""", [action, name, header])


def set_phase(root, name, phase):
    path = os.path.join(root, "projects", name, "state", "status.json")
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    st["phase"] = phase
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f)


def check_git(pw):
    root, _ = gw.make_workspace()
    config = tempfile.mkdtemp(prefix="aaf-desktop-")
    app = None
    remote = lambda n: gw.git(os.path.join(root, "remotes", n + ".git"), "log", "--format=%s", "main")
    try:
        app = App(pw, root, config)
        before = remote("example-done")
        code, _ = post(app, "push", "example-done", header=False)
        if code != 403 or remote("example-done") != before:
            problems.append("git: a push without the page's header was not refused (got %s)" % code)
        app.open("example-done")
        app.page.wait_for_selector('[data-git-action="push"]:not([disabled])', timeout=30000)
        app.page.click('[data-git-action="push"]')
        app.page.wait_for_function("() => !document.querySelector('[data-git-action=\"push\"]') || "
                                   "!/Pushing/.test(document.querySelector('[data-git-action=\"push\"]').textContent)", timeout=120000)
        app.page.wait_for_timeout(500)
        if "Tidy up after review" not in remote("example-done"):
            problems.append("git: the Push button in the window did not send the commits")
        if "Sent to GitHub" not in app.page.inner_text("body"):
            problems.append("git: the window does not say the push worked")
        app.page.screenshot(path=os.path.join(PLOTS, "render-desktop-git.png"))
        set_phase(root, "image-classifier", "checking")
        code, d = post(app, "pull", "image-classifier")
        if code != 409:
            problems.append("git: Pull while the agent works gave %s %r, expected 409" % (code, d))
        set_phase(root, "parser", "waiting")
        app.open("parser")
        app.page.wait_for_selector('[data-git-action="pull"]:not([disabled])', timeout=30000)
        app.page.click('[data-git-action="pull"]')
        app.page.wait_for_function("() => /Got the newest versions|Pull did not work/.test(document.body.innerText)", timeout=120000)
        info = app.page.evaluate("async () => (await (await fetch('/api/git?name=parser&fresh=1')).json()).behind")
        if info != 0:
            problems.append("git: the Pull button did not bring the newer commit (still %r behind)" % info)
        if app.errors:
            problems.append("git: JavaScript errors in the window: %s" % app.errors[:3])
    finally:
        if app:
            app.close()
        shutil.rmtree(config, ignore_errors=True)
        gw.remove_workspace(root)


def check_restart(pw, config, first):
    """Theme, colour-blind mode and the window's size and position survive a restart."""
    first.page.click("#theme")
    first.page.click("#palette")
    want = first.page.evaluate("[document.documentElement.dataset.theme, document.documentElement.dataset.palette || '']")
    if want != ["light", "cb"]:
        problems.append("restart: the switches did not turn on light and colour-blind (%r)" % want)
    hwnd = first.windows()[0][0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetWindowPos(hwnd, 0, 140, 90, 1500, 950, 0x0004)  # SWP_NOZORDER
    time.sleep(0.8)
    rect = first.windows()[0][3]
    first.close()
    second = App(pw, FIXTURES, config)
    try:
        got = second.page.evaluate("[document.documentElement.dataset.theme, document.documentElement.dataset.palette || '']")
        if got != want:
            problems.append("restart: theme and colour-blind mode were %r before and %r after" % (want, got))
        again = second.windows()[0][3] if second.windows() else None
        if again is None or max(abs(a - b) for a, b in zip(again, rect)) > 2:
            problems.append("restart: window was at %r, came back at %r" % (rect, again))
        second.page.screenshot(path=os.path.join(PLOTS, "render-desktop-after-restart.png"))
        if second.errors:
            problems.append("restart: JavaScript errors: %s" % second.errors[:3])
    finally:
        second.close()


def main():
    if os.name != "nt":
        print("SKIP: the desktop window check runs on Windows (WebView2)")
        return 0
    os.makedirs(PLOTS, exist_ok=True)
    try:
        app_server.build()
    except RuntimeError as e:
        print("FAIL: the app could not be built:", e)
        return 1
    check_netstat_sees_serve()
    config = tempfile.mkdtemp(prefix="aaf-desktop-")
    try:
        with sync_playwright() as pw:
            app = App(pw, FIXTURES, config)
            try:
                check_window(app)
                check_fixtures(app)
                app.open("api-client")
                app.page.screenshot(path=os.path.join(PLOTS, "render-desktop-window.png"))
                check_restart(pw, config, app)
            finally:
                app.close()
            check_git(pw)
    except Exception as e:
        problems.append("the window check stopped: %s" % str(e).splitlines()[0])
    finally:
        shutil.rmtree(config, ignore_errors=True)
    if problems:
        print("FAIL: desktop window:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: the app's own window (no browser, no network port) shows all nine fixtures without errors, "
          "Push and Pull work through it, and theme, colour-blind mode, size and position survive a restart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
