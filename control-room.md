# control-room

The Agent Control Room: a desktop app (Windows, and built for the Mac) with the live dashboard for every
project in this workspace.

## Purpose

Show, at a glance, what each project's agent is doing and whether the work is sound:
the current task, where the agent is in its loop, check results, the independent
review, drafts waiting for a decision, plots, decisions and progress. The audience
includes people who do not know the code behind it.

## How it works

- The core (`app/src/`, Rust; the router is `api.rs`; the earlier Python `server.py` answers the same until it
  is retired, and `checks/parity.py` compares them). It reads files from
  `<workspace>/projects/*/state/` and `*/plots/` and never writes them itself. Endpoints:
  `/` (the page), `/api/projects`, `/api/project?name=`, `/plot?project=&file=`,
  `/api/git?name=[&fresh=1]` (runs `framework/aaf.py git info <name> --fetch`, cached 15 s),
  `/api/files?name=[&fresh=1]` (the change map: `framework/aaf.py git files <name>`, cached 30 s,
  dropped after Push/Pull),
  and `POST /api/git/push|pull` with `{"name": ...}`. `/api/project` also carries the newest
  30 steps of `state/activity.jsonl` (the live feed, written by `framework/hooks/activity.py`),
  read from the end of the file; `activity_steps()` leaves out quiet records (`done`), counts a
  permission prompt once, and marks a `waiting` step `resolved` (+ `resolved_ts`) by `done`/`error`
  for the same `tool_use_id`, a `you` record or the next step by the same agent (notes and turn ends do not count); `/api/projects` carries each project's newest step, `trend` (share of
  tests passing in each of the last 12 runs, for the rail's tiny line) and `plan` (`state/plan.json`:
  steps done, total, the current step and every step's text; `null` without a plan).
  `/api/project` also carries `tasks`: the task timeline, i.e. `task_stats()` from `framework/aaf.py`
  (what `aaf.py stats <name>` prints), run in a subprocess on the project folder with the served
  workspace's aaf.py (or this workspace's, for a workspace without one, like the fixtures), cached
  until `state/events.jsonl` changes (a failed run is not cached), plus the events of the shown tasks for the segment details.
  `/api/project` also carries `record`: `state/review_history.jsonl` and the failed reviews grouped by
  theme (`REASONS` in `app/src/reasons.rs`: keywords in the one-line summary), each matched to the project's
  `DONE.md` item that covers it. `/api/record` is the workspace view ("All projects"): every project's
  task_stats summary and tasks (from the same cache) and the reasons across all projects.
  `/api/project` also carries `estimate`: `estimate()` from `framework/aaf.py` (what `aaf.py estimate <name>`
  prints: active, phase, elapsed_s, plan, progress_low/high, remaining_low_s/high_s, basis, history_tasks,
  history_scope, calibration) plus `held` (aaf's `_calibration()`, i.e. `estimate_accuracy` in `aaf.py stats`)
  and `available`, run in a subprocess with `aaf.PROJECTS` set to the served workspace, cached 15 s (a failed run too).
  `control-room serve --clock <time>` pins "now" inside that subprocess, so checks get fixed numbers.
  More endpoints of the app: `/api/workspaces` (+ `POST add|select|rename|remove`, and `pick` in the window),
  `/api/settings` (Python path, notification switches; in the window also start at login) and `/api/events`
  (what became true in any workspace, newest first).
- **Git is the one exception to read-only.** Push and Pull run
  `<workspace>/framework/aaf.py git push|pull <name>`, never `git` directly. Writes are
  accepted only from the page itself: the request must come from this machine, carry the
  header `X-AAF-Request: control-room`, use a localhost `Host`, and any `Origin` must be
  this server. Pull is refused (409) while the project's agent is planning, implementing,
  checking, reviewing or fixing.
- **The app** (`app/src/desktop.rs`, Tauri 2): one window, "Agent Control Room", showing the page through the
  app's own protocol (`http://app.localhost/`, the same router, no network port). Closing it hides it to the tray
  (dot on the icon while anything needs you, a menu per workspace, Quit); a second start shows the running
  window (lock file in the settings folder); start at login via the autostart plugin (off by default).
  `watch.rs` looks at every workspace every 5 s and raises events (waiting, decision, stuck, finished, failing),
  each once; in the window they become system notifications whose click opens that project. Settings and the
  workspace list live in `settings.json` in the app's settings folder (`%APPDATA%/Agent Control Room`;
  `--config` for checks). Debug builds answer `/api/debug/tray` and `/api/debug/open` for `checks/desktop.py`.
  `control-room serve [--root W] [--port N] [--clock ISO] [--config DIR]` is the same router over HTTP on
  127.0.0.1, for the checks and GitHub Actions. `python3 build.py` makes the icons from `design/icon.svg`
  (approved), raises the version and builds the per-user NSIS installer into `dist/`.
- `index.html`: the whole front end in one file (HTML, CSS, vanilla JS). It polls the
  API every 2.5 s and re-renders only when the data changed. Layout and look follow the approved
  design in `design/DESIGN.md` (reference: `design/mockup.html`, `design/mockup-dark.png`): a left
  rail with four workspace numbers (`/api/record` gives the first-try rate) and a tiny picture per
  project; a full-width hero (its right half, `[data-slot=estimate]`, is "How far along": the time
  estimate as a range, the plan, the basis, and gives way to the "what to do" card when the human is needed); then a
  12-column grid from 1200 px: step by step (5), tests (3), track record (4), where the time went
  (8), where the agent works (4); Git, pictures and more detail below. Under 1200 px one column.
- The data model is defined by `framework/aaf.py` (status phases, checks.json,
  check_history.jsonl, review.json, decisions.md, progress.md, events.jsonl, drafts).
  Read it before changing what the page expects.

## How to run

Install the app from the newest installer (`python3 build.py`, then `dist/Agent Control Room_<version>_x64-setup.exe`)
and open it from the Start menu. For development: `cd app && cargo run` opens the window (add `-- --root <workspace>`
to show one workspace for this run); `cargo run -- serve --root ../fixtures/workspace --port 8770` serves the fixtures
at http://127.0.0.1:8770. Rust (rustup) is needed; `build.py` also needs the Tauri CLI
(`cargo install tauri-cli --version "^2" --locked`). Until it is retired, `python3 dashboard/server.py` from the
workspace root still starts the browser version.

## How to check

`python3 framework/aaf.py check control-room` runs:
1. **Server API**: tests of the Rust core over HTTP (`control-room serve`, started by
   `checks/app_server.py`) against the fixture workspace (`tests/test_api.py`), the
   Git endpoints against a temporary workspace with real repositories (`tests/test_git.py`),
   that no check or test still imports `server.py` and no assertion was lost moving them to the
   core (`tests/test_core_only.py`),
   that each test file runs fully on its own (`tests/test_layout.py`), that built roadmap items
   stay marked done (`tests/test_roadmap.py`) and that `README.md` follows the template, names
   every part of the page and only points to files that exist (`tests/test_readme.py`), and that every
   colour in the page's styles comes from a token (`tests/test_colours.py`)
2. **Page renders in every state**: `checks/render.py` opens every fixture project (and
   `fixtures/first-run`) in a headless browser (desktop light, desktop dark, phone), fails on JavaScript errors or
   sideways scrolling, and writes screenshots to `plots/render-*.png`.
3. **Understandable at a glance**: `checks/glance.py` (summary first, plain words, detail on demand).
4. **Git section works**: `checks/git_section.py` builds a temporary workspace with real
   repositories, then checks the timeline colours, sync picture, repo link, Push and Pull,
   and saves `plots/render-git-*.png`.
5. **Live activity feed**: `checks/activity.py` pins the browser clock and checks the current
   step, the recent history, reviewer marks, the "waiting for you in Claude Code" state, waits
   resolved by `done` / `you` records, `error` and `you` steps, and the "gone quiet" notice; it saves `plots/render-activity-*.png`.
6. **Task timeline**: `checks/timeline.py` pins the clock and checks one bar per task (latest on
   top), one segment per stage in proportion to its time, one colour per stage, attempt marks,
   pause breaks, outcome and duration, the detail shown on tapping a segment, and that a running
   task grows; it saves `plots/render-timeline-*.png`.
7. **Change map**: `checks/change_map.py` builds a Git workspace (`checks/git_workspace.py`;
   `code_repo()` gives `scheduler` a small code tree with uneven change counts) and checks one tile
   per file grouped by folder, area from size, colour from change count, the bookkeeping toggle
   (remembered), the tile detail and the empty states; it saves `plots/render-map-*.png`.
8. **Track record**: `checks/track_record.py` pins the clock and checks, per fixture, the four numbers
   against `aaf.py stats`, one bar per task in proportion to its attempts, the marks for reviews, fixes
   set aside and stuck episodes, the tap detail, the reasons the review said no (expected counts written
   by hand) and their link to the definition of done; then the workspace view (totals, rows, reasons,
   opening a project) and an empty workspace; it saves `plots/render-record-*.png`.
9. **Instrument-panel layout**: `checks/layout.py` checks, for every fixture at 1440 × 900, that the hero
   and the five main panels are all fully on the first screen, the grid (row 2 about 5 : 3 : 4, row 3
   8 : 4; the "what to do" card in the hero's right half) and the design's section order; one column in
   the same order on phones; the rail's numbers and tiny pictures; dark by default and light after the
   switch (remembered); the DESIGN.md colour tokens in both themes; each phase drawn in its token's
   colour in the loop, the live steps and the timeline; the three fonts. It repeats the first-screen check
   on a temporary workspace with real Git repositories (`check_git`: real treemap, Git section below). It saves
   `plots/render-layout-desktop-{dark,light}.png` and `plots/render-layout-git-desktop-dark.png`. After a visual change, put that next to
   `design/mockup-dark.png` and compare (e.g. `plots/compare-mockup-dark.png`).
10. **Time estimate**: `checks/estimate.py` pins the server's and the browser's clock and checks, for every
   fixture and `fixtures/first-run`, the hero's "How far along": the range in per cent, the bar's solid part
   and striped band at progress_low/high, "about … to … left" against remaining_low/high_s, "step N of M"
   with the current step, the plain "based on" sentence with the number of past tasks (plan steps, review
   time, longer than almost every past task, not enough history yet), how often estimates held (hero and
   track record), no range without a running task, the "what to do" card in its place when the human is
   needed, plain words and phone width. It saves `plots/render-estimate-*.png`.
11. **Colour-blind mode**: `checks/colour_blind.py` checks the rail's `#palette` switch (off by default,
   `aria-pressed`, remembered as `aaf.palette = cb`), the colour-blind tokens from DESIGN.md in both themes
   (`:root[data-palette="cb"]`), that the loop, live steps and timeline use them, and, simulating protanopia,
   deuteranopia and tritanopia, that every pair of the seven state colours is at least 12 apart (CIEDE2000)
   and 3:1 against the panel. It saves `plots/render-colourblind-*.png`, including deuteranopia simulations.
12. **Rust core**: `cargo test` in `app/` (records, feed, reasons, caches with fake runners, the router and
   write guards, workspaces and settings, the needs-you rule, tray model, events).
13. **Same answers as before**: `checks/parity.py` compares every GET of `control-room serve` with `server.py` on
   four workspaces, push and pull, the page on `server.py`, and scans `app/src` for a `git` command (until the
   browser version is retired).
14. **Desktop window**: `checks/desktop.py` (Windows) drives the real window over CDP: window and no port, all
   fixtures, Push/Pull, restart memory, tray and dot, second start, hidden start, start at login, the
   notification-click route, sideways scrolling in the real window. Saves `plots/render-desktop-*.png`.
15. **Workspaces**: `checks/workspaces.py`: welcome, refusal, add, switch, rename, remove, restart, missing
   folder, Python line, switcher and gear fit the rail.
16. **Notifications**: `checks/notifications.py`: file changes on two workspace copies give one event each.
17. **Installer**: `checks/installer.py`: the newest installer in `dist/` for the current version, per user,
   Start-menu entry and desktop-icon hook, icons from `design/icon.svg` (run `python3 build.py` first).
18. **Smoke check**: `checks/smoke.py`: `serve` on the fixtures without the framework tool (also on GitHub).

GitHub Actions (`.github/workflows/build.yml`) runs the Rust tests, the build and the smoke check on Windows
and macOS on every push and keeps the installer and the `.dmg`.

The page is dark by default and ignores the browser's colour preference, so checks that need the
light theme store the switch's choice first (`localStorage aaf.theme = light`).

The render check needs Playwright once, installed into a local `.venv` in this folder:

```
cd projects/control-room
python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
```

**Always open the screenshots in `plots/` with the Read tool after a visual change.**
Passing the checks only proves nothing crashed; the screenshots show whether the page
is actually clear.

## Fixtures

`fixtures/workspace/projects/` holds nine projects, one per situation the page must
handle: `api-client` (finished, a long track record: nine tasks, six rejected reviews with repeated
reasons, a fix set aside, one stuck episode), `image-classifier` (running, failing a check, a plan
with 2 of 5 steps done), `parser` (waiting for a decision
on a draft), `example-done` (finished, with a plot and reviewer steps in its activity log),
`scheduler` (stuck), `brand-new` (nothing run yet, no activity log), `web-scraper`
(mid-task, Claude Code waiting for permission), `notes-app` (being reviewed, plan all done; its activity
log uses the hook's newer records: a permission granted by a quiet `done`, an `error`, a reply answered by `you`) and
`data-pipeline` (running about 19 h, longer than any past task). `fixtures/first-run/` is a
second workspace with one planning project and no finished task anywhere (the estimate's "not enough
history"). `api-client/state/estimates.jsonl` holds ten logged estimate ranges, seven of which held, so
the calibration has data; `image-classifier`'s plan (2 of 5 done) makes the mid-plan estimate. `state/activity.jsonl` in a fixture is
the live feed's data; its timestamps are fixed, so `checks/activity.py` pins the clock.
`state/events.jsonl` drives the task timeline: `example-done` has four tasks (finished first try,
stuck, stuck then resumed and finished, finished with a polish step), `image-classifier` a finished
and a running task, `parser` one that waits for a decision (its review history has one rejection that fits no theme, "Other"), `scheduler` one stuck after 8 attempts. If you add a new kind of state, add a fixture for it.

Git data is never stored in the fixtures. `checks/git_workspace.py` copies the fixtures
and `framework/aaf.py` into a temporary folder at test time, turns some projects into
repositories and adds a bare repository standing in for GitHub. aaf.py treats the folder it
sits in as the workspace, so this needs no changes to aaf.py.

## Conventions

- One file for the front end; no build step, no npm, no framework.
- External resources: only Google Fonts, and the page must still work without them.
- Colours and fonts are the tokens from `design/DESIGN.md`, as CSS variables on `:root` (dark, the
  default) and `:root[data-theme="light"]`. One colour per phase (`--plan`, `--change`, `--test`,
  `--review`, `--polish`), used the same everywhere; never hard-code a colour.
- The first screen at 1440 × 900 holds the hero and the five main panels; anything new goes below
  them or behind a fold, so `checks/layout.py` keeps passing.
- Plain language for people who don't know the code: say what is happening and why
  it matters, not internal names.

## Do not touch

- The app's core must not write project files itself (it writes only its own settings folder) and must
  keep rejecting path traversal. Its only change to a project is Git push/pull through `aaf.py`, behind the
  page-only checks. Never run `git` from the core (no `Command::new("git")` in `app/src`). The same holds
  for `server.py` until it is retired.
- Use the icon in `design/icon.svg` only as approved; a new design needs the human's approval again.
- `framework/aaf.py` is outside this project; ask before changing the data model.
