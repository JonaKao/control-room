# Spec: the control room as a desktop app (Rust, Tauri)

Agreed with the human on 2026-11-24.

## Goal

Make the Agent Control Room a real desktop app that you open from a desktop or
Start-menu icon. It runs in its own window, with no browser, no address bar and no
server to start by hand. It keeps watching from the system tray and tells you, with a
system notification, when a project needs you. The logic behind the page moves from
Python (`server.py`) to Rust. The page itself (`index.html`) and its approved design
stay, so everything the dashboard shows today keeps working.

## Decisions from the interview

| Question | Decision |
|---|---|
| How much in Rust | All of `server.py` is ported to Rust. `server.py` is retired at the end. `framework/aaf.py` stays Python and is still called as a subprocess. |
| Browser version | The app replaces it. `python3 dashboard/server.py`, `dashboard/` and `Open Dashboard.command` go away. |
| Background | Closing the window hides it to the system tray. Notifications arrive while the app runs. |
| Notify when | Claude Code waits for permission or a reply; a fix waits for a decision, or an agent is stuck; a task finished with the review passed; a project's checks go from passing to failing. |
| Workspaces | Several, one shown at a time. A switcher sits at the top of the rail. Notifications come from every workspace, and clicking one opens the right workspace and project. |
| Platforms | Windows and Mac. Windows is built and checked on this machine; Mac is built by GitHub Actions (the repository `JonaKao/control-room` is public, so macOS runners are free). |
| Updates | Rebuild and reinstall. Each task that changes the app ends with a new installer in `dist/`. Installing it is the human's step, or the agent's after asking. |
| Start at login | Optional, a switch in the settings, off by default. |
| Icon | The agent designs one in the control room's colours and shows it to the human as an image. It is used only after the human approves (recorded as a decision). |
| Rust toolchain | Not installed yet. The first task installs `rustup` (stable, MSVC) and the Microsoft C++ Build Tools, asking the human to approve each download first. |

## Scope

- A Tauri 2 app in `app/` with a Rust core that answers the same questions as `server.py` today.
- The same `index.html`, served by the Rust core. Changes to it are limited to what the
  app needs: the workspace switcher, the settings panel, the first-start screen.
- System tray, notifications, single instance, optional start at login.
- Several workspaces, remembered across restarts.
- Windows installer (per user, no admin, desktop and Start-menu shortcuts) and a Mac `.dmg`, both from GitHub Actions.
- Every existing check keeps passing, now against the Rust core.
- README, `control-room.md` and the workspace's own docs updated; the browser version removed.

## Out of scope

- Code signing and notarization. Windows SmartScreen will warn on first install ("More
  info → Run anyway"), and macOS needs right-click → Open the first time. The README says so.
- Automatic updates (the human chose rebuild and reinstall).
- Linux.
- Viewing from a phone or another computer. That ends with the browser version. The
  narrow (390 px) layout stays, because the window can be made narrow, and the phone-width
  checks keep running as narrow-window checks.
- Porting `framework/aaf.py` to Rust, or changing its data model.
- Showing several workspaces in one rail.

## Design

### Layout

```
projects/control-room/
  app/                      Cargo workspace (Tauri 2)
    Cargo.toml, Cargo.lock
    src/main.rs             starts the app, or `serve` mode (below)
    src/lib.rs
    src/records.rs          reading state/*.json, *.jsonl (tail reads), progress.md, decisions.md, plots
    src/activity.rs         activity_steps(): quiet records, duplicate prompts, resolved waits
    src/reasons.rs          REASONS themes, done_items(), review_reasons()
    src/aaf.rs              running framework/aaf.py (stats, estimate, git info/files/push/pull), caches, CLOCK
    src/api.rs              the router: every endpoint server.py has today, plus /api/workspaces and /api/settings
    src/workspaces.rs       the workspace list, current workspace, settings file
    src/watch.rs            notices events across all workspaces (for notifications and the tray)
    src/desktop.rs          window, custom protocol, tray, notifications, single instance, autostart (Tauri only)
    tauri.conf.json, icons/
  index.html                the page (stays at this path; the Rust core embeds it at build time)
  design/icon.svg           the icon's one source; icons/ is generated from it
  checks/app_server.py      helper: start `control-room serve` for the checks
  checks/desktop.py         end-to-end check of the real window (Windows)
  dist/                     built installers (ignored by Git)
  .github/workflows/build.yml
```

### One router, two ways in

`api.rs` holds one router (axum) with today's endpoints and JSON shapes, unchanged:
`/`, `/api/projects`, `/api/project?name=`, `/plot?project=&file=`, `/api/git?name=[&fresh=1]`,
`/api/files?name=[&fresh=1]`, `/api/record`, `POST /api/git/push|pull`. New endpoints:
`/api/workspaces` (list, current, which ones are available), `POST /api/workspaces/add|remove|select`,
`/api/settings` and `POST /api/settings`, and `/api/events` (what `watch.rs` noticed, newest first, for the
page and the checks).

- **In the app** the window loads the page through a Tauri custom protocol handled by
  that router. The app opens **no network port**, so nothing else on the machine can call Push or Pull.
- **`control-room serve --root <workspace> [--port N] [--clock ISO] [--config DIR]`** runs the same
  router over HTTP on 127.0.0.1, with no window. It exists for the checks (Playwright) and for
  GitHub Actions. It keeps today's write guards: local address, `X-AAF-Request: control-room`,
  a localhost `Host`, a matching `Origin`. `--clock` pins "now" the way `server.CLOCK` does today. `--config`
  points to a settings folder, so checks never touch the real one.

### Unchanged rules from `server.py`

- The core never writes project files. Its one change to a project is Git push and pull through
  `aaf.py git push|pull`, never `git` directly, and Pull is refused (409) while the agent is working.
- Paths outside the workspace are refused (names checked with today's `NAME_RE`, plots only from `plots/`).
- Derived data comes from `aaf.py`, with today's cache times (Git 15 s, files 30 s, estimate 15 s,
  stats until `events.jsonl` changes, failed runs cached too).
- The page polls every 2.5 s as today.

### Python

`aaf.py` needs Python. The core looks for it in this order: the path set in the settings, then
`python3`, `python`, and `py -3` (Windows). If none works, the page says so plainly in the places
that need it (timeline, track record, estimate, Git, change map), and the rest of the page still works.

### Workspaces and settings

Settings live in the app's own config folder (`%APPDATA%\Agent Control Room\settings.json`
on Windows, `~/Library/Application Support/Agent Control Room/` on Mac), or in `--config DIR`.
They hold the workspaces (path, display name), the current one, the Python path, start at login,
and one on/off switch per kind of notification (all on by default). The theme and colour-blind
switches stay in the page's local storage, as today.

A folder is a workspace if it holds `framework/aaf.py` and `projects/`. A workspace whose folder
is missing (moved, unplugged drive) stays in the list, marked "not found", and never crashes the app.

### Watching and notifications

`watch.rs` reads every workspace every 5 s, using the same reading code as the page. It raises an
event when one of these **becomes** true:

| Event | Becomes true when |
|---|---|
| `waiting` | The newest activity step is an unresolved `waiting` (permission or reply in Claude Code) |
| `decision` | The phase becomes `waiting` with unfinished drafts, or a new draft appears |
| `stuck` | The phase becomes `stuck` |
| `finished` | A task ends `done` with the review passed |
| `failing` | The newest check run fails where the one before passed |

Each event has a key (workspace, project, kind, and the step id, draft id or time of the change),
and each key is notified once. States that are already true when the app starts are not notified;
the rail already shows them. Clicking a notification opens the window on that workspace and project.

### Tray, window, single instance

- Closing the window hides it; the app keeps running in the tray (menu bar on Mac). The tray menu has
  "Open Agent Control Room", one entry per workspace with how many projects need you, and "Quit".
- The tray icon has a second version (a dot) while anything in any workspace needs you.
- Opening the app again (icon, Start menu) shows the running window instead of starting a second app.
- The window remembers its size and position.

### Building and installing

- `python3 build.py` (in the project folder) builds the release app and copies the installer to
  `dist/` (`Agent Control Room_<version>_x64-setup.exe` on Windows). The version in `tauri.conf.json`
  goes up by one patch number on every task that changes the app.
- The Windows installer is NSIS, installs per user without admin rights, and creates desktop and
  Start-menu shortcuts. Installing a newer version replaces the old one and keeps the settings.
- `.github/workflows/build.yml`, on every push: Windows and macOS runners run `cargo test`, build the
  app, run a smoke check (`serve` on the fixtures: every endpoint that does not need `aaf.py` answers
  as expected, path traversal refused), and upload the installer or `.dmg` as an artifact. Only the
  control-room repository is on GitHub, without `framework/aaf.py`, so the full checks run on this
  machine only.

### Checks

The page checks open the page in Playwright exactly as now, but against `control-room serve` (through
`checks/app_server.py`) instead of `import server` plus `ThreadingHTTPServer`. What `tests/test_api.py`
and `tests/test_git.py` test by patching Python internals (for example a failing subprocess being
cached) moves to Rust unit tests (`cargo test`). The source scan "the server never calls git" becomes a
scan of `app/src` for a `git` command. Moving a check to the new core is not weakening it: every
assertion keeps its meaning. Any assertion that cannot keep its meaning is recorded as a decision first.

New checks in `project.json`: **Rust core** (`cargo test`), **Same answers as before** (parity, only
until feature 10), **Desktop window** (`checks/desktop.py`), **Workspaces**, **Notifications**,
**Installer**. On Windows, `checks/desktop.py` starts the built app with WebView2's remote debugging
(`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=N`), a temporary `--config`, and the
fixture workspace, then connects Playwright with `connect_over_cdp`, so the real window is checked.

The checks have to run outside Claude Code's sandbox, as today (Chromium, and now WebView2 and cargo).

## Features

Built in this order. Each is one `/task control-room next`.

### 1. Rust core gives the same answers as server.py

Install the toolchain (asking first), create `app/`, and port `server.py` into the modules above with `serve` mode.

Acceptance:
- `cargo test` passes and covers `activity_steps` (every case in `ActivityStepsTest`), the review
  themes, tail reads of large JSONL files, the caches (including a failing `aaf.py` run being cached),
  path traversal and the write guards.
- New check **Same answers as before** (`checks/parity.py`): for every fixture project, `fixtures/first-run`
  and the temporary Git workspace (`checks/git_workspace.py`), with the clock pinned, every GET endpoint
  of `control-room serve` returns JSON equal to `server.py`'s (only differences listed in the check
  itself and recorded as a decision are allowed). It fails before the port exists.
- Push and Pull through `serve` give the same results and refusals as `tests/test_git.py` expects
  (409 while working, 403 without the header or from a foreign `Origin`).
- No `git` command anywhere in `app/src` (source scan).

### 2. All existing checks run against the Rust core

Acceptance:
- `checks/app_server.py` starts `control-room serve` on a free port with `--root`, `--clock` and
  `--config`; every browser check uses it, and none imports `server.py`.
- `tests/` no longer imports `server.py`; tests that needed its internals are now Rust unit tests or HTTP tests against `serve`.
- All eleven existing checks and **Rust core** pass, with no assertion removed or loosened. The number of
  assertions per check is not lower than before (the review compares).
- The screenshots in `plots/render-*.png` look as before (compared by eye, noted in progress.md).

### 3. Its own window

Acceptance:
- Starting the app (`control-room` without `serve`) opens a window titled "Agent Control Room" showing
  the page, with no address bar, tabs or browser menu, at least 1280 × 800 the first time, with size and position remembered.
- The app opens no listening TCP port (the check compares the process's listening ports with the OS).
- New check **Desktop window** (`checks/desktop.py`, Windows): on the fixture workspace the real window
  shows the rail with all nine fixture projects, opens each one without JavaScript errors, Push/Pull
  reach the core through the window (temporary Git workspace), and the theme and colour-blind choices
  survive a restart. It saves `plots/render-desktop-*.png`.

### 4. Several workspaces

Acceptance:
- First start with no workspaces: a welcome screen says what a workspace is and offers "Choose a
  folder…" (system folder picker). A folder without `framework/aaf.py` and `projects/` is refused with a plain reason.
- The rail starts with a workspace switcher showing the current workspace's name; picking another one
  shows its projects within one poll. Workspaces can be added, renamed and removed in the settings.
- The list and the current workspace survive a restart. A workspace whose folder is gone shows as
  "not found" and the app still starts.
- The settings panel (a gear in the rail) also holds the Python path, with a "found: Python 3.12 at …" line.
- New check **Workspaces**: via `serve --config <temp>` and the page, with two copies of the fixtures:
  add, select, rename, remove, refuse a non-workspace, a missing folder, and a restart. The first screen
  still passes `checks/layout.py` (switcher and gear fit in the rail).

### 5. Tray and background

Acceptance:
- Closing the window keeps the app running in the tray. "Quit" in the tray menu ends it.
- The tray menu lists each workspace with how many of its projects need you. The tray icon shows its
  dot version exactly while that number is above zero (unit test on the count; desktop check reads the tray state through a test hook in `serve`/debug builds).
- Opening the app a second time focuses the running window (desktop check: the second start exits and the first window comes to the front).
- "Start when I log in" in the settings, off by default, adds or removes the login entry (checked
  through the autostart plugin's own status, then switched back).

### 6. Notifications

Acceptance:
- **Notifications** check: Rust tests and a `serve` test copy the fixtures to a temporary folder, change
  their files the way `aaf.py` and the activity hook would (a new `waiting` step, phase `stuck`, a new draft,
  a task done with a passed review, a failing check run after a passing one), and expect exactly one
  event per change in `/api/events`. Nothing is raised for states already true at start, and nothing
  twice for the same change.
- Events come from every workspace in the settings, not only the current one.
- Each event becomes a system notification in plain words ("web-scraper is waiting for your permission
  in Claude Code"). Clicking it opens the window on that workspace and project. The desktop check
  confirms the open-on-click route; the notification itself is confirmed once by a screenshot.
- One switch per kind in the settings; a kind that is switched off raises no notification (but still appears in `/api/events`).

### 7. Icon and installer

Acceptance:
- `design/icon.svg` (the control room's colours, readable at 16 px) is shown to the human as a
  rendered PNG and used only after their approval, recorded with `aaf.py decide`. All sizes in
  `app/icons/` are generated from it.
- `python3 build.py` produces `dist/Agent Control Room_<version>_x64-setup.exe`. New check
  **Installer**: the file exists after a build, the bundle config asks for per-user install with desktop and
  Start-menu shortcuts, and the version is higher than the last one built.
- Installed once on this machine with the human's OK: a Start-menu entry and a desktop icon open the
  app (screenshot in `plots/`). Reinstalling a newer build keeps the workspaces and settings.

### 8. Mac build on GitHub

Acceptance:
- `.github/workflows/build.yml` runs on push on `windows-latest` and `macos-latest`: `cargo test`,
  the app build, the `serve` smoke check, and uploads the installer and `.dmg` as artifacts.
- A run after the push is green on both, checked with `gh run list` / `gh run view` and noted in progress.md with its link.
- The code has no Windows-only path without a Mac counterpart (Python lookup, config folder, tray, autostart).
- What could not be checked on a real Mac (the tray in the menu bar, notifications, Gatekeeper) is
  listed in the README and progress.md as unchecked.

### 9. Plain README for the app

Acceptance:
- README "How to run": download or build, install, first start (choose a workspace), the
  SmartScreen and Gatekeeper first-open steps, the tray and notifications, settings. "How it is built" describes
  `app/`, the one router and its two ways in, and the checks. `tests/test_readme.py` is updated to the
  new names (`control-room serve`, `build.py`, `app/`) and still fails when one is missing.
- `control-room.md` describes the new structure; `ROADMAP.md` gets item 9 "Desktop app" (Done).

### 10. Browser version retired

Acceptance:
- `server.py`, `dashboard/` (the shim and the old `index.html`) and `Open Dashboard.command` are removed;
  the workspace `README.md` and `framework/REFERENCE.md` point to the app instead (these files are outside
  the project; this spec allows changing them).
- The parity check **Same answers as before** is removed from `project.json`, recorded as a decision
  (it compared with `server.py`, which no longer exists). Every other check still passes.
- The DONE.md line about "the server" now says "the app's core", with the same meaning.

## Verification

The whole thing works when, on this Windows machine and without the Python server:

1. `python3 framework/aaf.py check control-room` passes every check (Rust core, the eleven page checks
   against `serve`, Desktop window, Workspaces, Notifications, Installer).
2. The installed app, opened from the Start menu, shows this real workspace and `fixtures/workspace` as two
   workspaces; switching between them works; closing the window leaves it in the tray.
3. Starting a `/task` in any project that hits a permission prompt makes a notification appear within
   about 10 s, and clicking it opens that project.
4. The latest GitHub Actions run is green on Windows and macOS and has the `.dmg` as an artifact.

## Open questions

- Mac behaviour (menu bar tray, notifications permission, Dock icon) is only built, not watched, until someone runs it on a Mac.
- Python on someone else's Mac: the app explains a missing Python, but does not install it.
- Unsigned installers: if SmartScreen/Gatekeeper warnings become a nuisance, signing is a later decision (it costs money for Mac).
