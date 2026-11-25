# control-room

The Agent Control Room: a desktop app that shows, live, what the coding agent in each
project of this workspace is doing and whether its work can be trusted, and tells you when one needs you.

## What it does

The [Agentic AI Framework](../../README.md) lets coding agents (Claude Code) work on
projects with little supervision: an agent plans a task, changes the code, runs the
project's tests, has an independent reviewer look at the result and repeats until the
project's definition of done holds. All of that is written to files in a records folder
inside each project. The control room reads those files and turns them into a page a person
can follow without knowing the code or the framework: what is happening now, whether
anything needs them, and how the work went.

The page is laid out like an instrument panel: everything important fits on the first screen
of a laptop, and detail opens when you ask for it. It is dark by default; the round button at
the top of the left rail switches to a light version and remembers the choice. The eye button
next to it turns on a colour-blind mode: the colours for each stage, passing and failing change to
ones that people with red-green or blue-yellow colour blindness can tell apart (passing becomes
blue, failing orange). It works with both versions and is remembered too.

**The left rail** shows four numbers for the whole workspace (how many projects need you, how
many are working, how many have finished, and how often tasks were right the first time), then
the projects grouped into "Needs you", "Working", "Finished" and "Not started", with "All
projects" on top. Each project carries a tiny picture: a progress bar while its agent works,
otherwise a line of how its recent test runs went.

**Picking a project** shows, on the first screen:

- **At a glance** (the summary, across the full width): the project, what the agent is doing in
  one plain sentence, which attempt it is on, a pill that says "Needs you" or "Nothing needs
  you", the task, a "Right now" line with its latest step and how long ago, and the agent's loop
  as a row of steps (Plan → Change → Test → Review → Finished, Your call or Stuck). Its right half,
  "How far along", shows how far a running task has got and how long is left, always as a range
  and never as a single number: a big "28–45% done", a bar whose solid part is the least it has done
  and whose striped band is how much further it may be, and "about 1 to 2 hours left". Beneath it:
  which step of the agent's written plan it is on, what the range is based on (the plan steps
  finished so far, how long past tasks or their reviews took, and how many past tasks), and how
  often earlier estimates held. With too few finished tasks to learn from it says "not
  enough history yet" and shows only the plan; a task already running longer than almost every
  past one is called a rough guess. Without a running task it shows the agent's note and plan.
  Someone who reads only this part knows what is going on and whether to act.
- **What to do** appears only when something needs you, in the summary's right half: unfinished
  fixes the agent set aside, each with its two choices (continue or discard) and the command to
  copy, or advice when the agent is stuck or waits for permission in Claude Code.
- **Step by step**: the live activity feed. The latest step in large type, the eight before it
  with the time, and the rest behind a fold. Each kind of step has an icon in the colour of its
  stage (reading and searching grey, changing blue, testing amber, reviewing violet); steps taken
  by the independent reviewer carry a "Reviewer" badge. When Claude Code waits for your permission or
  reply it says so plainly, and calms down again as soon as you answered (the step ran, you sent a
  message, or the next step started). A step that did not work is marked red, with what went wrong
  one tap away; your own messages in Claude Code appear as steps too. When a running task has sent
  no step for five minutes it says the feed has gone quiet.
- **Tests**: a ring with how many tests pass, each test with a tick or cross and how long it took, every earlier test
  run as a small bar, the reviewer's verdict and how many attempts were used. Test output and the
  full review are one tap away.
- **Track record**: how well the agent does over time. Four numbers (tasks right the first time,
  reviews that said no, fixes set aside, times stuck), how often the time estimates held (across
  all projects, at the top of the panel) and a small chart of attempts per task; tap a
  bar for that task. "Why the review said no" opens the reviewer's rejections grouped by theme, most
  common first, each with a hint on what to sharpen in the project's instructions or definition of
  done. "All projects" in the rail shows the same across the whole workspace.
- **Where the time went**: the task timeline. One lane per task, latest on top, split into coloured
  segments for planning, making a change, testing, being reviewed and polishing (fixing the
  reviewer's small points afterwards), with marks where a new attempt began, a hatched break where
  the task stood still, the outcome and the working time. Tapping a segment tells what happened in
  it; a running task's lane grows while you watch. Older tasks wait behind a fold.
- **Where the agent works**: the change map. Every file of the project as a tile, grouped by
  folder; a bigger tile is a bigger file, a stronger blue one was changed more often. Tapping a tile
  shows its last change. The framework's own records (progress notes, test results, screenshots)
  are hidden unless you ask for them.

Below the first screen:

- **Saved versions (Git)**: this computer ⇄ GitHub (versions to send, versions to get, unsaved
  files), Push and Pull buttons, a link to the repository, and a timeline of the saved versions
  coloured by whether tests passed and the review approved; a dashed ring marks each version GitHub
  does not have yet. Pull is refused while the agent is
  working. Hidden when the workspace has no framework tool.
- **Pictures from the project**: plots the project produced, when there are any.
- **More detail**, folded away: the decision log, the agent's progress note and the full activity
  log.

One colour stands for each stage everywhere on the page (the loop, the live steps, the timeline,
the rail). The page updates itself every few seconds. On a phone it becomes one column in the same
order, with the summary first and the project list as one row of chips.

## How to run

The control room is a desktop app for Windows (and, untested so far, the Mac). It opens in its own
window, keeps watching from the tray and tells you with a notification when a project needs you.

**Get the installer.** Either take it from GitHub: open the repository's Actions tab, click the newest
"build" run and download `agent-control-room-windows-latest` (or `agent-control-room-macos-latest`)
under Artifacts; or build it yourself on Windows, from this folder:

```
python3 build.py
```

That needs Rust (from rustup.rs) and, once, the Tauri tool (`cargo install tauri-cli --version "^2" --locked`).
It leaves `Agent Control Room_<version>_x64-setup.exe` in the dist folder.

**Install on Windows.** Run `Agent Control Room_<version>_x64-setup.exe`. It installs for you only, without
admin rights, and puts the app in the Start menu and on the desktop. The installer is not signed, so the
first time Windows may show "Windows protected your PC" (SmartScreen): click **More info**, then
**Run anyway**.

**Install on a Mac** (Apple silicon). Open the `.dmg` and drag the app into Applications. The app is not
signed, so the first time macOS refuses to open it (Gatekeeper): right-click (or Control-click) the app,
choose **Open**, then **Open** again. After that it opens normally.

**First start.** The app asks for your workspace: the folder of the Agentic AI Framework, the one that holds
the folders `framework` and `projects`. Click **Choose a folder…** and pick it (or type where it is). The list
on the left then shows every project; the top of the page says what the agent is doing and whether anything
needs you.

**Every day.**
- Closing the window does not end the app: it keeps running in the tray (the notification area next to the
  clock; the menu bar on a Mac). Its icon gets a dot while a project needs you. Click the icon to open the
  window; its menu lists each workspace with how many projects need you, and **Quit** ends the app.
- A notification appears when Claude Code waits for your permission or reply, a fix waits for your decision,
  a project is stuck, a task finished and the review approved it, or tests that passed start failing.
  Clicking it opens that project (on Windows).
- Opening the app again (Start menu, desktop) brings its window back instead of starting a second one.

**Settings** (the gear at the top of the list on the left):
- Workspaces: add more (each is a folder of the framework), rename them, remove them from the list (the
  folders stay as they are). The switcher at the top of the list on the left changes between them.
- Python: the timeline, the time estimate, Git and the change map come from the framework's own tool, which
  needs Python 3. The app finds it by itself; if it cannot, type where Python is.
- Notifications: one switch per kind.
- **Start when I log in**: off at first; when on, the app starts in the tray each time you log in.

**Updating.** Install a newer installer over the old one; your workspaces and settings are kept (they live
in the folder Agent Control Room inside %APPDATA% on Windows, and inside Library/Application Support in your home
folder on a Mac).

**Without a window** (for the checks and for development): `control-room serve --root <workspace>` answers
the page's questions on this computer only (http://127.0.0.1, port 8765 or `--port`), with no window;
`--config <folder>` uses another settings folder, `--clock <time>` pins "now" for the time estimate. The
checks need Rust and, once, Playwright:

```
cd projects/control-room
python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
```

(On Windows the programs are in .venv\Scripts instead of .venv/bin.) Until it is retired, the older browser
version still starts from the workspace root with `python3 dashboard/server.py`.

## How it is built

- `app/`: the desktop app, in Rust with Tauri (see `specs/desktop-app.md` for how it was planned). Its core
  reads each project's `state/` and `plots/` folders and answers the page's questions as JSON. It never
  writes project files and refuses paths outside the workspace. Derived data comes from the framework rather
  than being recomputed: the task timeline and track record from `framework/aaf.py stats`, the time estimate
  from `aaf.py estimate`, the change map from `aaf.py git files`, the Git section from `aaf.py git info`
  (run with Python, cached so polling stays cheap). The only thing it changes in a project is Git, and only
  through `aaf.py git push|pull`, only for the page itself. The parts, in `app/src/`: reading the records
  (`records.rs`), the live feed's steps (`activity.rs`), why reviews said no (`reasons.rs`), the framework tool
  and its caches (`aaf.rs`), the router (`api.rs`), the workspace list and settings (`workspaces.rs`), what
  needs you and what changed, for the tray and notifications (`watch.rs`), and the window, tray, notifications,
  single instance and start at login (`desktop.rs`).
  **One router, two ways in**: the same answers reach the window through the app's own protocol (no network
  port, so nothing else on the computer can push or pull), and reach the checks through
  `control-room serve`, over HTTP on 127.0.0.1, with the page's own header required for any change.
  `python3 build.py` makes the icons in `app/icons/` from `design/icon.svg`, raises the version and builds the
  installer into the dist folder (`Agent Control Room_<version>_x64-setup.exe`, per user, with a Start-menu
  entry and a desktop icon).
  What the app adds around the page: its own window, the tray (with Quit), a workspace switcher and the
  settings (workspaces, Python, notifications, start when you log in), kept in `settings.json` in the app's
  settings folder (`--config <folder>` points it elsewhere, which the checks use). Its own checks:
  `checks/desktop.py` drives the real window on Windows (window, tray, second start, start at login, the route
  a notification click takes), `checks/workspaces.py` adds, switches, renames and removes workspaces,
  `checks/notifications.py` changes project files the way the agent does and expects one notification each,
  `checks/installer.py` checks the newest installer in the dist folder, and `checks/smoke.py` checks the core
  without the framework tool.
- `server.py`: the earlier browser version (a standard-library Python server for the same page), kept until it
  is retired; `checks/parity.py` confirms the app's core answers exactly as it did.
- `.github/workflows/build.yml`: on every push to GitHub, Windows and macOS machines there run the Rust
  tests, build the app (the Windows installer and a Mac `.dmg`), run `checks/smoke.py` on it and keep the
  installer and the `.dmg` (for Macs with Apple silicon) as downloads of that run. Only this project is on GitHub, without the framework,
  so the full checks run on the developer's Windows computer. Not yet tried on a real Mac: the icon in the
  menu bar and its menu, notifications (and the permission a Mac asks for them; clicking one does not open the
  project there), starting at login, the first opening of an unsigned app (Gatekeeper: right-click, Open),
  and how the window and Dock behave.
- `index.html`: the whole page in one file (HTML, CSS and plain JavaScript, no build step,
  no libraries). It asks the server for fresh data every 2.5 seconds and redraws only what
  changed. Its colours and fonts are the tokens from the approved design.
- `design/`: the approved design. `design/DESIGN.md` sets the layout, colour and type rules;
  `design/mockup.html` and its screenshots are the reference the page is compared with.
- `fixtures/`: a pretend workspace with nine projects, one for each situation the page
  must handle (running mid-plan, running longer than any task before, being reviewed, stuck,
  waiting for a decision, waiting for permission, finished, never started, a long track
  record), and `fixtures/first-run`, a workspace where no task has finished yet. Git repositories are never stored there; the checks
  build them in a temporary folder with `checks/git_workspace.py`.
- `tests/`: tests of the core's answers over HTTP, its Git safety rules, this README, and that every colour
  comes from the design's tokens.
- `checks/`: scripts that open the page in a headless browser for every fixture (desktop
  light, desktop dark, phone), fail on errors or sideways scrolling, test each section's
  behaviour, and save screenshots to `plots/` for a person or agent to look at.
  `checks/layout.py` checks the design itself: the summary and the five main panels all on the
  first 1440 × 900 screen (on the example projects and on a temporary workspace with real Git
  repositories), the panel grid and order, one column on phones, dark by default, and the design's colours
  and fonts.
  `checks/colour_blind.py` checks the colour-blind mode: the switch, its colours in both versions,
  and, by simulating the three common kinds of colour blindness, that every pair of colours stays
  clearly apart. Its screenshots include the page as someone with deuteranopia sees it.
- `ROADMAP.md`: the planned features (activity feed, task timeline, change map, track record,
  README, the instrument-panel redesign, the time estimate, the use of the framework's 2026-10-19
  updates and the desktop app) and their status. See
  [ROADMAP.md](ROADMAP.md).

How it fits into the Agentic AI Framework: agents record their progress only through
`framework/aaf.py` (phases, test runs, reviews, decisions, drafts, Git), and
`framework/hooks/activity.py` logs each step they take to the project's activity log. The
control room is the read side of those records. It is itself a project in the workspace,
with its own `CLAUDE.md`, `DONE.md` and checks, so agents improve it with `/task` like any
other project.

## How it is checked

<!-- aaf:checks:start -->
Every change must pass these before it is committed:

- **Server API**: `python3 -m unittest discover -s tests -q`
- **Page renders in every state**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/render.py; else python3 checks/render.py; fi`
- **Understandable at a glance**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/glance.py; else python3 checks/glance.py; fi`
- **Git section works**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/git_section.py; else python3 checks/git_section.py; fi`
- **Live activity feed**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/activity.py; else python3 checks/activity.py; fi`
- **Task timeline**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/timeline.py; else python3 checks/timeline.py; fi`
- **Change map**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/change_map.py; else python3 checks/change_map.py; fi`
- **Track record**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/track_record.py; else python3 checks/track_record.py; fi`
- **Instrument-panel layout**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/layout.py; else python3 checks/layout.py; fi`
- **Time estimate**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/estimate.py; else python3 checks/estimate.py; fi`
- **Colour-blind mode**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/colour_blind.py; else python3 checks/colour_blind.py; fi`
- **Rust core**: `cd app && PATH="$HOME/.cargo/bin:$PATH" cargo test --quiet`
- **Same answers as before**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/parity.py; elif [ -x .venv/Scripts/python.exe ]; then .venv/Scripts/python.exe checks/parity.py; else python3 checks/parity.py; fi`
- **Desktop window**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/desktop.py; elif [ -x .venv/Scripts/python.exe ]; then .venv/Scripts/python.exe checks/desktop.py; else python3 checks/desktop.py; fi`
- **Workspaces**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/workspaces.py; elif [ -x .venv/Scripts/python.exe ]; then .venv/Scripts/python.exe checks/workspaces.py; else python3 checks/workspaces.py; fi`
- **Notifications**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/notifications.py; elif [ -x .venv/Scripts/python.exe ]; then .venv/Scripts/python.exe checks/notifications.py; else python3 checks/notifications.py; fi`
- **Installer**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/installer.py; elif [ -x .venv/Scripts/python.exe ]; then .venv/Scripts/python.exe checks/installer.py; else python3 checks/installer.py; fi`
- **Smoke check**: `if [ -x .venv/bin/python ]; then .venv/bin/python checks/smoke.py; elif [ -x .venv/Scripts/python.exe ]; then .venv/Scripts/python.exe checks/smoke.py; else python3 checks/smoke.py; fi`
<!-- aaf:checks:end -->

## History

Finished tasks, newest first. Generated from the project's records on every commit.

<!-- aaf:history:start -->
- 2026-11-25: F9: Plain README for the app (first try, review passed)
- 2026-11-25: F8: Mac build on GitHub (first try, review passed)
- 2026-11-25: F7: Icon and installer (first try, review passed)
- 2026-11-25: F6: Notifications (2 attempts, review passed)
- 2026-11-25: F5: Tray and background (first try, review passed)
- 2026-11-25: F4: Several workspaces (3 attempts, review passed)
- 2026-11-24: F3: Its own window (first try, review passed)
- 2026-11-24: F2: All existing checks run against the Rust core (first try, review passed)
- 2026-11-24: F1: Rust core gives the same answers as server.py (2 attempts, review passed)
- 2026-11-24: Create a colour-blind mode (first try, review passed, a follow-up fix is waiting for a decision)
- 2026-10-19: Use framework updates: per-commit pushed flag, done/you/error activity records, per-test durations (review passed)
- 2026-10-19: Roadmap 7: show how far along a running task is and how long is left (time estimate) (first try, review passed)
- 2026-10-17: Roadmap 6: redesign the page as an instrument panel (design/DESIGN.md): rail with workspace numbers, hero, 12-column panel grid, dark by default (first try, review passed)
- 2026-10-15: Write README.md for the control room from the template: what it is, each part of the page, how to start, how it is built, how it fits the framework (first try, review passed)
- 2026-10-15: Roadmap 4: add a track record (per-project and workspace view, common review-failure reasons) (2 attempts, review passed)
- 2026-10-15: Roadmap 3: add a change map (treemap of files from aaf.py git files) (first try, review passed)
- 2026-10-15: Roadmap 2: add a task timeline (per-task bars split into phases, from aaf.py stats) (first try, review passed)
- 2026-10-14: Roadmap 1: live activity feed from state/activity.jsonl (3 attempts, review passed)
- 2026-10-14: Add a visual Git section: commit timeline, sync state, repo link, Push/Pull buttons (3 attempts, review passed)
- 2026-10-14: Redesign the layout so a newcomer sees at a glance what the agent is doing and whether anything needs them (4 attempts, review passed)
<!-- aaf:history:end -->
