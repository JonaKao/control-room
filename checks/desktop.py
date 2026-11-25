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
  restarting the app;
- with no workspace yet, the window welcomes and offers the system folder picker ("Choose a folder…");
- closing the window keeps the app in the tray; the tray menu lists each workspace with how many projects
  need you and its icon has the dot exactly while that is above zero (read through the debug build's test
  hook); a second start shows the running window and ends; "Quit" in the tray ends the app;
- "Start when I log in" is off by default and switches the login entry on and off (plugin status and the
  Windows Run entry), and the machine's own entries are put back afterwards.
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

    def __init__(self, pw, root, config, first_start=False, extra=()):
        self.port = free_port()
        env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=%d" % self.port)
        args = [app_server.EXE, "--config", config] + (["--root", root] if root else []) + list(extra)
        self.proc = subprocess.Popen(args, env=env,
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
        if first_start:
            self.page.wait_for_selector("[data-ws-welcome]", timeout=20000)
        else:
            self.page.wait_for_selector("#projects .proj", timeout=20000)
            try:  # the first project's detail, not just the rail
                self.page.wait_for_selector("main [data-section]", timeout=30000)
            except Exception:
                problems.append("the window showed the project list but no project in 30 s")
        self.page.wait_for_timeout(500)
        deadline = time.time() + (3 if "--hidden" in extra else 10)
        while not self.windows() and time.time() < deadline:
            time.sleep(0.2)

    def windows(self):
        return [w for w in windows_of(self.proc.pid) if w[1]]

    def open(self, name):
        """Open a project the way a person does: click it in the rail."""
        self.page.click('#projects .proj[data-p="%s"]' % name)
        self.page.wait_for_function("n => (document.querySelector('#projects .proj[aria-current=\"true\"]') || {}).dataset?.p === n",
                                    arg=name, timeout=15000)
        # Its first opening runs aaf.py for the timeline and estimate: wait for the project itself, not a fixed time.
        try:
            self.page.wait_for_function("n => !!document.querySelector('main [data-section]')"
                                        " && document.querySelector('main').innerText.includes(n)", arg=name, timeout=20000)
        except Exception:
            pass  # the caller reports what the window shows
        self.page.wait_for_timeout(300)

    def current(self):
        return self.page.evaluate("(document.querySelector('#projects .proj[aria-current=\"true\"]') || {dataset: {}}).dataset.p")

    def close_window(self):
        """Close the window like a person would (WM_CLOSE): the app keeps running in the tray."""
        for w in self.windows():  # only the app's window; Tao's hidden event window must stay
            user32.PostMessageW(w[0], 0x0010, 0, 0)  # WM_CLOSE

    def tray(self):
        """The tray's menu and icon, from the debug build's test hook."""
        return self.page.evaluate("fetch('/api/debug/tray').then(r => r.json())")

    def tray_choose(self, item):
        return self.page.evaluate("""id => fetch('/api/debug/tray', {method: 'POST', headers: {'Content-Type': 'application/json',
            'X-AAF-Request': 'control-room'}, body: JSON.stringify({id})}).then(r => r.status)""", item)

    def close(self, gracefully=True):
        """End the app the way a person does: "Quit" in the tray (it saves its state); kill if it hangs."""
        if self.proc.poll() is None and gracefully:
            try:
                self.tray_choose("quit")
            except Exception:
                pass
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                problems.append("the app did not end within 15 s of Quit in the tray")
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


def visible(hwnd):
    return bool(user32.IsWindowVisible(hwnd))


def wait_tray(app, cond, seconds=12):
    """The tray is recounted every 5 s: wait until `cond(tray)` holds; return the last tray seen."""
    deadline, t = time.time() + seconds, None
    while time.time() < deadline:
        t = app.tray()
        if cond(t):
            return t
        time.sleep(0.5)
    return t


def check_tray(pw):
    """Closing hides to the tray; the tray lists each workspace with how many projects need you, and its
    icon carries the dot exactly while that number is above zero; a second start shows the window; Quit ends."""
    tmp = tempfile.mkdtemp(prefix="aaf-tray-")
    root, config = os.path.join(tmp, "calm"), os.path.join(tmp, "config")
    shutil.copytree(os.path.join(FIXTURES, "projects", "brand-new"), os.path.join(root, "projects", "brand-new"))
    status = os.path.join(root, "projects", "brand-new", "state", "status.json")
    os.makedirs(os.path.dirname(status), exist_ok=True)

    def set_phase(phase):
        with open(status, "w", encoding="utf-8") as f:
            json.dump({"phase": phase, "task": "Tray test", "updated": "2026-10-14T12:00:00+02:00"}, f)
    set_phase("idle")
    app = None
    try:
        app = App(pw, root, config)
        hwnd = app.windows()[0][0]
        t = wait_tray(app, lambda t: any("calm" in i["label"] for i in t["items"]))
        labels = [i["label"] for i in t["items"]]
        if labels != ["Open Agent Control Room", "calm — nothing needs you", "Quit"] or t["dot"]:
            problems.append("tray: with nothing needing you the menu is %r and the dot is %r" % (labels, t["dot"]))
        set_phase("waiting")
        t = wait_tray(app, lambda t: t["dot"])
        if not t["dot"] or "calm — 1 needs you" not in [i["label"] for i in t["items"]]:
            problems.append("tray: a project waiting for a decision did not show (dot %r, menu %r)" % (t["dot"], t["items"]))
        set_phase("idle")
        t = wait_tray(app, lambda t: not t["dot"])
        if t["dot"]:
            problems.append("tray: the dot stayed after nothing needed you any more")
        # Closing the window keeps the app running, hidden in the tray.
        app.close_window()
        time.sleep(1.5)
        if app.proc.poll() is not None:
            problems.append("tray: closing the window ended the app (exit code %s)" % app.proc.poll())
            return
        if visible(hwnd):
            problems.append("tray: the window is still visible after closing it")
        # Starting the app again shows the running one instead of a second app.
        env = dict(os.environ)
        second = subprocess.Popen([app_server.EXE, "--root", root, "--config", config], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            code = second.wait(15)
        except subprocess.TimeoutExpired:
            second.kill()
            code = "still running after 15 s"
        if code != 0:
            problems.append("second start: it did not hand over and end (%s)" % code)
        deadline = time.time() + 5
        while time.time() < deadline and not visible(hwnd):
            time.sleep(0.2)
        if not visible(hwnd):
            problems.append("second start: the running app's window did not come back")
        elif user32.GetForegroundWindow() != hwnd:
            problems.append("second start: the window came back but not to the front")
        app.page.screenshot(path=os.path.join(PLOTS, "render-desktop-tray-back.png"))
        # The tray's workspace entry opens the window on that workspace.
        app.close_window()
        time.sleep(1)
        app.tray_choose("ws:0")
        time.sleep(1.5)
        if not visible(hwnd):
            problems.append("tray: choosing the workspace in the tray menu did not open the window")
        app.close()
        if app.proc.poll() is None:
            problems.append("tray: Quit did not end the app")
    finally:
        if app:
            app.close(gracefully=False)
        shutil.rmtree(tmp, ignore_errors=True)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def run_entries():
    import winreg
    out = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        i = 0
        while True:
            try:
                name, value, kind = winreg.EnumValue(k, i)
            except OSError:
                return out
            out[name] = (value, kind)
            i += 1


def restore_run_entries(before):
    import winreg
    after = run_entries()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name in after:
            if name not in before:
                winreg.DeleteValue(k, name)
        for name, (value, kind) in before.items():
            if after.get(name) != (value, kind):
                winreg.SetValueEx(k, name, 0, kind, value)


def check_login(pw):
    """"Start when I log in": off by default, the switch turns the login entry on and off (the autostart
    plugin's own status, and the Windows Run entry it writes); the machine's entries are restored after."""
    before = run_entries()
    config = tempfile.mkdtemp(prefix="aaf-login-")
    app = None
    try:
        app = App(pw, FIXTURES, config)
        app.page.click("#gear")
        app.page.wait_for_selector("#settings[open] [data-settings=login]:not([hidden])", timeout=15000)
        state = lambda: app.page.evaluate("fetch('/api/settings').then(r => r.json()).then(d => d.start_at_login)")
        ours = lambda: [n for n, (v, _) in run_entries().items() if os.path.normcase(app_server.EXE) in os.path.normcase(v)]
        mine_before = [n for n, (v, _) in before.items() if os.path.normcase(app_server.EXE) in os.path.normcase(v)]
        if not mine_before:
            if state() is not False or app.page.is_checked("[data-login]"):
                problems.append("login: 'Start when I log in' is not off by default")
        app.page.screenshot(path=os.path.join(PLOTS, "render-desktop-settings.png"))
        app.page.click("[data-login]")
        app.page.wait_for_timeout(800)
        if state() is not True or not ours():
            problems.append("login: switching it on did not add the login entry (plugin %r, Run entries %r)" % (state(), ours()))
        elif not all("--hidden" in run_entries()[n][0] for n in ours()):
            problems.append("login: the login entry does not start the app hidden in the tray: %r" % [run_entries()[n][0] for n in ours()])
        app.page.click("[data-login]")
        app.page.wait_for_timeout(800)
        if state() is not False or ours():
            problems.append("login: switching it off did not remove the login entry (plugin %r, Run entries %r)" % (state(), ours()))
        if app.errors:
            problems.append("login: JavaScript errors: %s" % app.errors[:3])
    finally:
        if app:
            app.close()
        restore_run_entries(before)
        shutil.rmtree(config, ignore_errors=True)


def check_hidden_start(pw):
    """Started by the login entry (--hidden): no window until it is opened from the tray."""
    config = tempfile.mkdtemp(prefix="aaf-hidden-")
    app = None
    try:
        app = App(pw, FIXTURES, config, extra=["--hidden"])
        if app.windows():
            problems.append("hidden start: the window is shown although the app was started for the tray")
        app.tray_choose("open")
        deadline = time.time() + 5
        while time.time() < deadline and not app.windows():
            time.sleep(0.2)
        if not app.windows():
            problems.append("hidden start: 'Open Agent Control Room' in the tray did not show the window")
    finally:
        if app:
            app.close()
        shutil.rmtree(config, ignore_errors=True)


def check_first_start(pw):
    """No workspace yet: the window welcomes and offers the system folder picker ("Choose a folder…")."""
    config = tempfile.mkdtemp(prefix="aaf-desktop-")
    app = None
    try:
        app = App(pw, None, config, first_start=True)
        pick = app.page.query_selector("[data-ws-welcome=first] [data-ws-pick]")
        if not pick or "Choose a folder" not in pick.inner_text() or not pick.is_visible():
            problems.append("first start: the window offers no 'Choose a folder…' button")
        if not app.page.evaluate("fetch('/api/workspaces').then(r => r.json()).then(d => d.can_pick === true)"):
            problems.append("first start: the window says it has no folder picker")
        app.page.screenshot(path=os.path.join(PLOTS, "render-desktop-first-start.png"))
        if app.errors:
            problems.append("first start: JavaScript errors: %s" % app.errors[:3])
    finally:
        if app:
            app.close()
        shutil.rmtree(config, ignore_errors=True)


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
            check_first_start(pw)
            check_tray(pw)
            check_hidden_start(pw)
            check_login(pw)
    except Exception as e:
        problems.append("the window check stopped: %s" % str(e).splitlines()[0])
    finally:
        shutil.rmtree(config, ignore_errors=True)
    if problems:
        print("FAIL: desktop window:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: the app's own window (no browser, no network port) shows all nine fixtures without errors, closes to the tray, "
          "Push and Pull work through it, and theme, colour-blind mode, size and position survive a restart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
