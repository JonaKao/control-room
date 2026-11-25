# Progress

## Current state

- **Desktop app F9: plain README for the app (2026-11-25)**: README "How to run" now explains the app for someone
  new: getting the installer (GitHub Actions artifacts or `python3 build.py`), installing on Windows (SmartScreen:
  More info, Run anyway) and on a Mac (Gatekeeper: right-click, Open), the first start (Choose a folder…), the tray,
  notifications, the settings (workspaces, Python, notifications, Start when I log in), updating (settings kept),
  and `control-room serve` for the checks; the browser version is mentioned only as "until it is retired". "How it
  is built" leads with `app/` (its parts, one router with two ways in: the window's own protocol and `serve`),
  `build.py`, the app's checks and the GitHub workflow; `server.py` is the earlier version kept for the parity check.
  `tests/test_readme.py` asks for these names (failed on the old README); `tests/test_roadmap.py` asks for item 9.
  `control-room.md` describes the core, the app, how to run it and all 18 checks; ROADMAP item 9 "Desktop app" Done.
- **Desktop app F8: Mac build on GitHub (2026-11-25)**: `.github/workflows/build.yml` runs on every push on
  windows-latest and macos-latest: `cargo test`, the Tauri CLI, `cargo tauri build` (NSIS / dmg), `checks/smoke.py` on
  the release program, and uploads the installer and the `.dmg`. First run green on both:
  https://github.com/JonaKao/control-room/actions/runs/45626493353 (60 Rust tests and the smoke check on each,
  `Agent Control Room_0.1.2_x64-setup.exe` 2.9 MB, `Agent Control Room_0.1.2_aarch64.dmg` 3.6 MB as artifacts).
  New check **Smoke check** (`checks/smoke.py`, also run locally): serve on the fixtures, everything that needs no
  aaf.py, refusals and the write guard. Platform review: every Windows-only path has its Mac counterpart (decision
  recorded); the tray now opens its menu on any click on a Mac. Unchecked on a real Mac (also in the README): the
  menu-bar icon and menu, notifications and their permission (no click route there), start at login, Gatekeeper's
  first opening of the unsigned app, window and Dock behaviour; the `.dmg` is for Apple silicon only.
- **Desktop app F7: icon and installer (2026-11-25)**: the human approved `design/icon.svg` (the page's logo ring on the
  dark panel); `python3 build.py` makes every size in `app/icons/` (PNG, ICO, ICNS) from it when it changed, raises the
  version above the last build (`dist/builds.json`), runs `cargo tauri build` (Tauri CLI installed with cargo; the
  bundler downloads NSIS once) and copies the installer to `dist/`. NSIS: per user, no admin, Start-menu entry, and a
  desktop icon from `app/windows/hooks.nsh`. New check **Installer** (`checks/installer.py`): installer for the current
  version, builds rising, per-user and shortcuts in the generated script, icons from the SVG; failed before the first
  build. Installed on this machine with the human's OK: 0.1.0, opened from the Start-menu entry
  (`plots/render-installed-start-menu.png`, window only); 0.1.1 installed over it: settings.json unchanged byte for
  byte, uninstall entry says 0.1.1, a cold start from the desktop icon shows the human's workspace
  (`plots/render-installed-desktop-icon.png`). The installed window showed a horizontal scrollbar on real data (the
  change map's "Show its own records (110)" button could not shrink); fixed (the button shrinks, full text as tooltip)
  and `checks/desktop.py` now checks for sideways scrolling in the real window at 1280 and 1215 px (failed first).
  The installed app's settings hold the human's own workspace (added in its window), left as they are.
  The desktop check's "came back to the front" asked for keyboard focus, which Windows only gives to the program the
  person used last: it passed twice, then failed every time from a background run. The app now lifts the window above
  the others when asked (second start, tray, notification), and the check asks for the first place in the stacking
  order (decision recorded). 0.1.2 is built in dist/ with that change; 0.1.1 is what is installed.
  Review minor fixed: the Installer check now requires the desktop-icon hook (Tauri's own shortcut is optional).
- **Desktop app F6: notifications (2026-11-25)**: `watch.rs` looks at every project of every workspace in the settings
  every 5 s (in the app and in `serve`) and raises an event when something becomes true: an unanswered wait that needs
  you (the page's rule), a new draft or the phase becoming waiting with drafts, stuck, done with a passed review, a test
  run failing right after a passing one. Each event has a key (workspace, project, kind, step/draft/time) and is
  raised once; the first look at a project (also at the start) raises nothing. `/api/events` lists them newest first.
  Settings: one switch per kind (`notify` in settings.json; the window's settings show them); a kind switched off is
  listed with `notify: false` and sends nothing. In the app each event with notify becomes a Windows notification in
  plain words ("notes-app is stuck and needs your help", "Workspace: demo. Click to open it."); clicking it selects the
  workspace and reloads the window on that project (Mac: the notification plugin, without the click). Choosing a
  workspace in the tray now takes the same route (F5 note). New check **Notifications** (`checks/notifications.py`):
  two fixture copies, five changes, exactly five events, none at start, none twice, the switch, none after a restart
  (caught a planted "no finished events"). `checks/desktop.py` also checks the click route from the hidden window to
  another workspace's project and the five switches. A real notification was shown once and captured, cropped to the
  notification (`plots/render-desktop-notification.png`). Not seen by a check: clicking a real notification.
  Review minor fixed (second attempt): a draft and the later waiting phase of one /fix give one decision notification;
  drafts are keyed per save (id, created, rounds) because ids come back.
- **Desktop app F5: tray and background (2026-11-25)**: closing the window hides it to the tray; "Quit" ends the app
  (saving size and position). Tray menu: "Open Agent Control Room", one entry per workspace ("name — 2 need you",
  "nothing needs you", "folder not found"; choosing it shows that workspace) and "Quit"; the icon gets an amber dot
  exactly while anything in any workspace needs you (`watch.rs`, the page's own rule, recounted every 5 s). A second
  start shows the running window and ends (lock file in the settings folder). "Start when I log in" in the settings
  (window only), off by default; the login entry starts the app hidden in the tray (`--hidden`). Debug builds answer
  `/api/debug/tray` for the checks. `checks/desktop.py` now also checks: close keeps the app in the tray, menu and dot
  both ways on a temporary workspace (caught a planted "dot only above 1"), a second start brings the window back to
  the front, the tray's workspace entry and "Open" show the window, a hidden start, Quit, and the login switch through
  the plugin's status and the Windows Run entry (machine entries restored afterwards). Rust tests for the rule (the
  fixtures: parser, scheduler, web-scraper) and the tray model. Screenshots looked at: `render-desktop-settings.png`,
  `render-desktop-tray-back.png`. Not seen by a check: how the tray icon and its dot look on the taskbar.
- **Desktop app F4: several workspaces (2026-11-24)**: `workspaces.rs` keeps the list in `settings.json` (config
  folder); the core shows the current one (`Core::with_workspaces`; `--root` only for the run). Endpoints
  `/api/workspaces` (+ `add`, `select`, `rename`, `remove`, `pick` in the window) and `/api/settings` (Python path and
  "Found: Python 3.x at ..."). Page: a workspace switcher at the top of the rail (name, list with "not found", "Add,
  rename or remove…"), a gear opening the settings dialog (rename, remove, add by path or "Choose a folder…" in the app,
  Python), a welcome screen on first start (what a workspace is), and a "folder was not found" screen. `serve` runs
  without `--root` too. A folder counts as a workspace when it has `projects/` (decision: the fixtures have no aaf.py).
  New check **Workspaces** (`checks/workspaces.py`, serve + page, two fixture copies): welcome, refusal, add, switch
  within one poll, rename, remove, restart, missing folder, Python line and its contrast, switcher and gear fit the
  rail at 1440 and 390 px; fails on the pre-F4 page. `checks/desktop.py` also checks the window's first start offers
  "Choose a folder…". Fixed on the way: stale polls drawing the previous project after a click; the picture viewer's
  dark text rule leaking into the settings dialog. Screenshots looked at: `render-workspaces-{welcome,switcher,settings,
  missing,phone}.png`, `render-desktop-first-start.png`. Not automated: the system folder picker itself (a native
  dialog); the button and `can_pick` are checked.
  Review 2 FAIL: the page needed `/api/workspaces`, so on `server.py` (the browser version, live until F10) it stayed on
  the welcome screen. Fixed in iteration 3: a 404 there means one workspace and no switcher; `checks/parity.py` now
  opens the page on `server.py` and expects the nine fixtures and no switcher (failed before the fix). README updated
  for F4 (its test asks for the switcher, settings, `--config` and `checks/workspaces.py`).
  Also: screenshot writes in every check now wait up to 10 s when Windows briefly holds the PNG (OSError errno
  22/13 broke three full runs); `checks/app_server.py` routes Playwright's `screenshot(path=...)` through
  `write_file` (decision recorded, reviewed PASS).
- **Desktop app F3: its own window (2026-11-24)**: `app/` is now a Tauri 2 app. `control-room` (no `serve`) opens
  one window, "Agent Control Room", 1280 x 800 the first time, showing the page from the app's own protocol
  (`http://app.localhost/`, `desktop.rs` answers with the same `Core::get`/`Core::post` as `serve`; writes need the
  page's header). No TCP port. Size and position are remembered (`<config>/window-state.json`, window-state plugin);
  theme and colour-blind mode live in WebView2's storage in `<config>/webview`. Options: `--root` (until feature 4,
  else the workspace it runs from or was built in) and `--config`. `app/icons` is a generated placeholder until F7.
  New check **Desktop window** (`checks/desktop.py`, Windows only): starts the real app with WebView2 remote debugging
  and a temporary config, connects Playwright over CDP; one titled window of the app's own process whose page fills
  the client area, at least 1280 x 800, no listening port (netstat, shown to see `serve`'s port), all nine fixtures
  opened by clicking the rail without JS errors, Push/Pull buttons in the window on a Git workspace (plus 403 without
  the header, 409 while working), and theme, colour-blind mode, size and position kept across a WM_CLOSE + restart.
  Fails when the app has no window. Review minor fixed: the README's `app/` paragraph now describes the window
  (guarded by `test_describes_the_desktop_window`). Also: `checks/app_server.py` stops every core it started when
  the check exits, so a crashing check no longer leaves a `serve` that locks the program for the next build.
  Screenshots looked at: `render-desktop-{window,web-scraper,image-classifier,git,after-restart}.png`.
- **Desktop app F2: checks and tests on the Rust core (2026-11-24)**: every page check (render, glance, Git,
  activity, timeline, change map, track record, layout, estimate, colour-blind) starts `control-room serve` through
  `checks/app_server.py` (`Served(root, clock=...)`, `.base`, `.shutdown()`, `get_json`); render serves
  `fixtures/first-run` with a second core instead of switching roots. `tests/test_api.py` and `tests/test_git.py` talk
  to `serve` over HTTP; what needed server.py's insides is a named Rust unit test (`rust_test`, one `cargo test` per
  process), plus an HTTP version where it keeps its meaning (decision recorded). New `tests/test_core_only.py`: nothing
  in checks/ or tests/ imports server.py (only `checks/parity.py`, until F10), every page check starts the core, and no
  file has fewer assertions than before the move (Rust asserts counted where they went); it fails on the pre-F2 files.
  Screenshots compared with the ones server.py rendered: 39 of 86 byte-identical; the rest differ only where the real
  clock or a fresh Git workspace shows (running times, progress percent, commit time and hash), checked by eye on
  parser, example-done Git and data-pipeline.
- **Desktop app F1: Rust core (2026-11-24)**, from `specs/desktop-app.md`. Rust (rustup, stable MSVC) and the
  Microsoft C++ Build Tools are installed on this machine (the human approved both); the human turned off Windows
  Smart App Control, which blocked every program cargo builds (os error 4551).
  `app/` is a Cargo package (`control-room`) that ports all of `server.py`: `records.rs` (reading `state/`, tail
  reads, trend, plan, plots), `activity.rs` (the feed's steps and waits), `reasons.rs` (review themes, DONE.md items),
  `aaf.rs` (Python lookup: settings path, `python3`, `python`, `py -3`; task_stats, estimate, Git info/files/push/pull
  through `aaf.py` with server.py's caches and single-run Git fetch; timestamps parsed like `fromisoformat`),
  `api.rs` (the router: `Core::get`/`Core::post`, write guards, axum over 127.0.0.1), `py.rs` (Python's truthiness,
  `str()`, `int()`, `==`, `strip()` and text-mode newlines, so records read exactly as before), `workspaces.rs`
  (settings folder), `main.rs` (`control-room serve --root <ws> [--port N] [--clock ISO] [--config DIR]`, prints
  "Serving on http://127.0.0.1:<port>"). `index.html` is built into the program. For a workspace without
  `aaf.py` (the fixtures) the timeline and estimate use the `aaf.py` of the workspace the program runs from or was
  built in, as server.py did. One deliberate difference: plot names must be one plain file name (a name with a
  drive, `C:x.png`, read outside `plots/` in both servers; the core refuses it; decision recorded).
  New checks: **Rust core** (`cargo test`: 45 tests: every ActivityStepsTest case, themes, tail reads, caches with
  fake runners, traversal, write guards, raw HTTP bad lengths) and **Same answers as before** (`checks/parity.py`:
  212 GET requests on fixtures, first-run, a long-log copy and a Git workspace, pinned clock, no differences
  allowed; push/pull on twin Git workspaces as `tests/test_git.py` expects; the drive-name refusal; no
  `Command::new("git")` in `app/src`). `checks/app_server.py` builds the app once per process and starts
  `serve` on a free port with a temporary `--config`. The checks now need Rust installed (`~/.cargo/bin`).
  Review 1 FAIL (this note was missing; drive-letter plot names), fixed in iteration 2.
- **Colour-blind mode (2026-10-30)**: an eye button in the rail, next to the theme switch (`#palette`,
  `aria-pressed`, remembered as `aaf.palette`), sets `data-palette="cb"` on `<html>`. Two token blocks in
  `index.html` (dark and light) swap only the seven state colours and the accent; surfaces, text and lines
  stay. Passing is blue, failing orange. DESIGN.md has a "Colour-blind mode" table. New check
  `checks/colour_blind.py` (registered as "Colour-blind mode"): the switch, the tokens in both themes, that the loop,
  live steps and timeline use them, every fixture without JS errors and no sideways scrolling on phones, and
  a simulation (Machado 2009 protan/deutan/tritan, CIEDE2000): every pair of the seven colours at least 12
  apart and 3:1 against the panel. The default palette fails that measurement (change/review 1.4 under
  deuteranopia), which the check also asserts. Screenshots inspected: `render-colourblind-desktop-{dark,light}.png`,
  `render-colourblind-phone.png`, `render-colourblind-deuteranopia-{default,cb}.png`.
  Limits: with seven colours the closest pairs sit around 13 (fail/test, change/review under deuteranopia);
  pushing one pair apart pulled another together, so the mode relies on the existing non-colour cues too
  (icons in the tests list, text and grouping in the rail).
  Note: the checks need to run outside Claude Code's sandbox (Chromium cannot start inside it); one full
  run had "Live activity feed" fail under load (70 s instead of 25 s); it passed alone and in the next full run.
  Review PASS with four notes and no minor findings, so there was no follow-up fix step. The notes are left for
  the human (see Next, first item).
- **Framework updates (roadmap 8, 2026-10-19)**, from `FRAMEWORK-UPDATES.md`:
  1. Git timeline: the dashed "not on GitHub yet" ring comes from each commit's own `pushed` field
     (`aaf.py git info`); only `false` draws it (`null`: no upstream). The "newest `ahead`" guess is gone.
     `checks/git_section.py` `check_pushed_field` patches a history where the unsent commits are not the newest.
  2. Activity feed: `server.activity_steps()` turns the hook's records into steps: quiet `done` records are
     never listed; Claude Code's id-less notification about a permission prompt right after the same prompt
     logged with its `tool_use_id` counts once; a `waiting` step is marked `resolved` (`done`/`error` for the
     same `tool_use_id`, `you`, or the next step; another step's error does not count) with `resolved_ts`.
     `read_activity()` reads 3 × 30 + 10 records so the feed still gets 30 steps. The page: a resolved wait
     is calm ("You gave permission: …", "Asked for your reply; you answered", right now "Carrying on with
     your permission"), never "Needs you" (hero, card, rail), and "gone quiet" counts from `resolved_ts`.
     `error` records are steps with a red warning icon and "What went wrong" (folded on the current step,
     tooltip in the list); `you` records are steps with a person icon. Fixture: `notes-app` got an activity
     log in the new format (granted permission as its latest step, an error, a reply). Checks:
     `ActivityStepsTest` (7 tests) and `checks/activity.py` (notes-app block); all fail on the old code.
  3. Tests panel: each test shows its time ("0.8 s", "1 min 14 s", "under 0.1 s") from `duration_s`;
     fixture durations made realistic; `checks/layout.py` `check_test_times` checks every fixture.
  Screenshots inspected: `render-activity-notes-app-desktop.png`, `render-layout-desktop-dark.png`.
  Review PASS (4 minor). Follow-up fix kept after a second PASS: the duplicate prompt counts once in either
  order, and notes, turn ends and other agents' steps no longer close a wait (two new ActivityStepsTest tests).
  Second follow-up fix kept after a PASS: `checks/layout.py` `check_many_test_times` (patched: eight tests, some
  folded, one without a time, values at the unit boundaries) and "59.6 s" now reads "1 min", "9.96 s" "10 s".
- **Time estimate (roadmap 7, 2026-10-19)**: the hero's right half "How far along" (`[data-slot=estimate]`)
  shows, for a running task, a range and never a single number: "28–45% done" in large type, a bar whose solid
  part ends at progress_low and a striped band to progress_high (phase colour), "about 1 to 2 hours left"
  (minutes, half hours, whole hours from 10 h, days from 4 days), "Step 3 of 5: <current step>", "started
  N min ago", a plain "based on" sentence with the number of past tasks and where they come from (plan steps,
  review time, "already running longer than almost every one of the 14 past tasks … a rough guess", or "Not
  enough history yet"), a window of three plan steps and the agent's note on one line; the header says
  "estimates held 7 of 10 times (all projects)". Without enough history it shows the plan bar and the full plan instead.
  When the human is needed the "what to do" card still takes that half. The track record's header adds
  "time estimates held 7 of 10 times (70%)" (across all projects; empty state as a line). Server:
  `/api/project` → `estimate` = aaf's `estimate()` + `held` (`_calibration()`), subprocess with
  `aaf.PROJECTS` set to the served workspace, cached 15 s; `server.CLOCK` pins "now" for checks (decision).
  New fixtures: `notes-app` (in review), `data-pipeline` (running 19 h, longer than any task before), `fixtures/first-run` (no history),
  `api-client/state/estimates.jsonl` (calibration); `image-classifier`'s task start and plan times now match its
  events. New check `checks/estimate.py`; `tests/test_api.py` EstimateTest; render check also renders
  `fixtures/first-run`; fixture lists in `tests/test_api.py` and `checks/glance.py` updated for the two new
  fixtures. Screenshots `plots/render-estimate-*.png` inspected; the full first screen
  (`render-estimate-desktop-dark.png`) matches the mockup's layout. Found while inspecting: with the real clock
  the fixtures' estimates read "123.5 to 281.5 hours"; fixed and now checked.
  Review PASS (5 minor points); follow-up fixes kept after a second PASS: the "based on" wording (no doubled
  "from", no plan mentioned when there is none, no fixed history size), the held line says "(all projects)", a
  failed estimate run is cached 15 s like a good one, and `data-pipeline` now runs longer than any past task.
  Open: no fixture shows "not enough history" together with a plan, so that sentence is not rendered by a check.
- The dashboard lives in this project; `dashboard/server.py` is a shim that starts `server.py` here.
- **Instrument-panel redesign (roadmap 6, 2026-10-17)**, after the approved design in `design/DESIGN.md`
  (reference `design/mockup.html`, `design/mockup-dark.png`; comparison images `plots/compare-mockup-{dark,light}.png`).
  Dark by default (the browser preference is ignored), light through the round button in the rail, remembered.
  DESIGN.md tokens (`--plan/--change/--test/--review/--polish/--pass/--fail`, surfaces, ink) and fonts (IBM Plex Sans
  Condensed, Inter Tight, JetBrains Mono, with system fallbacks). One colour per phase everywhere: loop stepper, live
  step icons (reading/searching grey, editing blue, tests and commands amber, reviewer violet), timeline, rail, hero edge.
  Rail: four workspace numbers (need you, working, finished, first try from `/api/record`) and a tiny picture per
  project (progress bar from the plan, or the loop stage, while working; otherwise the last 12 test runs as a line;
  server: `/api/projects` → `trend`, `plan`). Hero full width: name, what it does, attempt chip, needs pill, task,
  "Right now", loop stepper; right half "How far along" (`[data-slot=estimate]`): agent's note and the plan's steps
  (window of five, done/current). When the human is needed, the "what to do" card takes that right half (hero and
  card 6 + 6 columns). From 1200 px a 12-column grid: step by step (5, still 8 recent steps), tests (3: ring, up to 5
  tests with the rest folded, run history strip, review and attempts), track record (4: four numbers, compact attempts
  chart, reasons behind "Why the review said no"), where the time went (8: compact lanes, 3 shown, the rest folded),
  where the agent works (4: the treemap fills the height its row leaves, at least 70 px, redrawn when that
  height changes; the "show its own records" toggle sits in the panel header; tile minimum about 30 x 30 px); then Git, pictures, more detail. The
  separate "Test runs over time" section is now the strip in the tests panel. Under 1200 px one column; phone as
  before (summary first, project chips in one row). New check `checks/layout.py` (all fixtures: hero and the five
  panels fully inside 1440 x 900, grid spans, order, phone column, theme, tokens, phase colours, fonts); fixture
  `image-classifier` got a plan (2 of 5 done). Three checks' order assertions follow the new order; checks that need
  light store the theme choice; the reasons fold is opened by the track record check before reading (see decisions).
  Also fixed before the task: the README test read the generated "How it is checked" commands as file references.
  Review PASS (5 small points). Follow-up fixes: `checks/layout.py` also runs on a temporary workspace with real Git
  repositories (`check_git`: scheduler, example-done, parser; real treemap and Git section, screenshot
  `plots/render-layout-git-desktop-dark.png`), which showed the map panel pushing row 3 below 900 px, hence the
  filling treemap above and the two "what to do" choices side by side on wide screens; the track record shows one line
  ("No review has happened yet" / "has not said no") instead of an empty "Why the review said no" fold
  (`checks/track_record.py` asserts it); the plot background and picture viewer use tokens (`--plot-bg`, `--plot-ink`,
  `--backdrop`) and `tests/test_colours.py` fails on any colour written outside the token blocks. Kept as is: the Git
  timeline's amber for "tests passed, not reviewed" (it is about testing, so the testing colour fits).
- *Superseded by the redesign above:* **Redesigned layout (2026-10-14)**, built for people who don't know the code. Top to bottom:
  1. **At a glance**: project, a "Needs you / Nothing needs you" pill, one plain sentence on
     what the agent is doing, the task, the agent's latest note, and a picture of the loop
     (Plan → Change → Test → Review → Finished / Your call / Stuck) with the attempt count.
  2. **What to do** (only when something needs the human): unfinished fixes with two
     choices and copyable commands, or guidance when the agent is stuck.
  3. **Is the work sound?**: test donut with ✓/✗ per test, review badge, attempt pips.
  4. **Test runs over time**: bar chart, one bar per run.
  5. **Pictures from the project** (plots), when there are any.
  6. **More detail**, collapsed: decisions, the agent's notes, the full activity log.
     Test output and the full review report are collapsed inside their tiles.
- Project list groups projects by "Needs you / Working / Finished / Not started", with an
  overview bar on top. On phones it becomes a single row of chips that scrolls sideways on
  its own, so even a long list never pushes the summary off the first screen (checked with 35 projects).
- Stuck projects: the loop shows the steps it went through in grey (tried, never passed) and
  the last step in red; the card says whether it used all its attempts or kept hitting the same
  problem, and points to the failing test's output. The last step's hint names the outcome.
- Phase names, event text, the task and the agent's notes are reworded in plain words: "iteration" → attempt,
  "checks" → tests, draft ids → unfinished fix N, framework files → "the progress note", "the decision log" etc.
- **Live activity feed (roadmap 1, 2026-10-14)**: the summary has a "Right now" line (name-free words
  per kind of step, how long ago). A "Step by step" section follows the summary (or the "What to do"
  card): the latest step large with its icon, the 8 before it newest first with an icon per kind
  and time, the rest of the recent steps (server sends 30) in a closed block. Steps by the reviewer
  carry a "Reviewer" badge. A latest "waiting" step needs the human when it is a permission request
  or comes mid-task: summary flag "Needs you in Claude Code", a "What to do" card, and the project
  moves to "Needs you" in the list. After a finished task the idle prompt is calm ("Idle in Claude
  Code, ready for a new task"; see the decision). A running task with no step for 5 min or more says
  the feed has gone quiet; while a task runs the page re-renders every 30 s so this appears without
  new data (otherwise only when data changes, so selected text is not dropped).
  While quiet, the summary says "Probably nothing needs you, but it has been quiet for N min". A stuck
  or decision-waiting project keeps its own message and red/blue dot; a waiting step only adds
  "· Claude Code is waiting for your reply".
  `tests/test_layout.py` makes sure each test file's `__main__` block comes last, so running a
  test file directly runs all of it.
  New fixture `web-scraper` (waiting for permission); activity logs in `image-classifier` and
  `example-done`; `brand-new` shows the empty state. Check: `checks/activity.py` (pins the clock).
- **Task timeline (roadmap 2, 2026-10-14)**: section "Where the time went" right after "Is the work
  sound?". One row per task, latest on top: name, outcome pill (Finished / Waits for your decision /
  Stuck / Still running), start, attempts, paused time; a bar split into one segment per stage
  (colours `--ph-plan/change/test/review/fix`, light and dark), a line with the number where a new
  attempt starts, a hatched fixed-width break where the task stood still between a stop and a resume,
  an end mark (✓ / ! / ✕ / pulsing dot) and the working time beside it. Bars share one working-time
  scale with an axis below (see decision). Tapping a segment shows the stage, attempt, times,
  duration, the agent's note and what was recorded in it (test runs, review verdicts, decisions,
  saved unfinished fixes); tapping a pause says how long and why it stopped. A running task's bar
  grows every 5 s without new data and keeps the open segment. More than 6 tasks: the rest behind
  "N earlier tasks". Empty state when no task has run.
  Data: `/api/project` → `tasks`, from aaf.py `task_stats()` in a subprocess, cached until
  events.jsonl changes (see decision). A failed run is not cached; event times are compared as times
  (logs may mix time zone offsets). Fixture event logs rewritten in the framework's current
  structured format with realistic times. Check: `checks/timeline.py`; API tests: `TimelineTest`.
- **Change map (roadmap 3, 2026-10-15)**: section "Where the agent works" after the Git section.
  A squarified treemap of the project's files from `aaf.py git files` (via `/api/files`, cached 30 s,
  loaded separately like the Git info): grouped by top-level folder (label drawn on the group; deeper
  folders show in the tile name), tile area from file size (tiny files get a minimum so they can be
  tapped), colour in five blue steps by how many saved versions changed the file (1, 2, 3-4, 5-8, 9+)
  with a legend. Tapping a tile shows its path, size, how many versions changed it, lines changed and
  its last change with the date. The agent's own records (state/, plots/) are hidden by default; a
  button shows them, remembered in the browser. Empty states: not a Git repository yet; workspace
  without the framework tool; only records and no code; the history could not be read (says so and
  retries every minute, instead of claiming the project has no Git). Tapping a tile (or Enter) keeps keyboard focus on it without moving the page.
  Files with no counted change (older
  than the 500 commits read) are grey with their own legend entry. Redrawn on resize.
- **Track record (roadmap 4, 2026-10-15)**: section "Track record" after "Test runs over time". Four numbers
  (right the first time, of the tasks that ended; reviews that said no, fixes set aside, times stuck; from aaf.py stats
  `summary`), an attempts-per-task bar chart (oldest left, colour = outcome, marks below for each review
  approved/said no, fix set aside, stuck episode; tapping a bar shows the task and why the review said no during
  it), and "Why the review said no": failed review summaries from `state/review_history.jsonl`, grouped by theme
  in server.py (`REASONS`, keywords), most common first, "Other" last, each with what to sharpen; when the
  project's definition of done already has a matching item, the page quotes it and says to make it more specific
  or back it with a test. **Workspace view**: "All projects" at the top of the project list (`#p=*`): totals, a
  sentence naming the most common reason, one row per project (most rejected reviews and stuck episodes first,
  first-try and rejection meters, attempts sparkline; tap opens the project), projects without tasks named,
  and the reasons across projects with where they were seen. Data: `/api/project` → `record`, `/api/record`.
  New fixture `api-client` (nine tasks, six rejections); parser's review history now has its rejection.
  Check: `checks/track_record.py`; API tests: `TrackRecordTest`; render check also renders the workspace view.
  aaf.py's `finished` counts every task that ended (finished, stuck or waiting), so where some ended stuck or
  waiting the page says "tasks that ended (finished, stuck or waiting for you)" instead of "finished tasks", and
  the chart caption says how many attempts a task usually takes "before it ends"; `checks/track_record.py`
  checks this per project and in the workspace view.
  In "All projects" each reason says whose definition of done already covers it (`covered_in`, from each
  project's DONE.md) and gives the generic advice only for the others; when one review named several reasons,
  a note says the counts add up to more than the rejections (`rejections`). Checked in `checks/track_record.py`
  (`check_overlap` uses a temporary workspace) and `TrackRecordTest`.
  `tests/test_roadmap.py` fails if a built roadmap item is not marked done (ROADMAP.md was found reset to
  "Not started" for all four items by something outside this task, during the first review; restored).
- **Git section ("Saved versions")**, after the test history: a picture of this computer ⇄ GitHub
  (versions to send / to get, unsaved files with the list on demand), Push and Pull buttons, a link
  to the repo, and a commit timeline (oldest left; green = tests passed and review approved, amber
  = tests passed but not reviewed, red = a test or the review failed, grey = no record; dashed
  ring = not on GitHub yet). Picking a point shows the subject, tests, review and decisions.
  Data comes from `aaf.py git info --fetch`; Push/Pull run `aaf.py git push|pull`, only from the
  page itself; Pull is refused while the agent works. Hidden when the workspace has no aaf.py.
  The Review trailer is read the same way for the colour and the detail, whatever its case or spacing
  ("Review: PASS" is approved; values other than pass/fail count as not reviewed); `checks/git_section.py`
  checks this with PASS, " Fail " and "skipped".
  The Git screenshots (`plots/render-git-*.png`) show one screen scrolled to the Git section, as a person
  sees it; the check fails if a saved screenshot is not exactly one screen (a full-page capture put the
  sticky project list mid-page).
  Git API tests that push, pull or change a phase (`GitWriteTest`) get a fresh workspace each; the read
  tests share one. `GitTestOrderTest` runs them in reverse order to prove they don't depend on order.
  Git info is cached 15 s per project (counted from when the fetch finished); requests arriving
  during a run share its answer, even when the fetch takes longer than 15 s. After Push/Pull the page
  asks for fresh data, which never reuses a fetch that started before it asked.
  Write requests whose stated body length is negative, above 4096 bytes or not a number get 400 at once.
- Checks: server API tests (now also `tests/test_git.py`, on a temporary Git workspace); a headless render of all five fixtures (screenshots of
  all of them in `plots/`); and `checks/glance.py`, which checks the glance summary is first,
  fits the first screen on desktop and phone, says what the agent does and whether the
  human is needed, uses no file names or internal terms, shows the visuals, and keeps
  detail behind closed blocks. It fails if a fixture folder is added without saying
  whether that situation needs the human.

- **README (2026-10-15)**: `README.md` written from the workspace template for someone who has never
  seen the project: what the control room is, every part of the page in the page's own order and
  titles, how to start it (also on the fixtures), how it is built (server, page, fixtures, tests,
  checks, ROADMAP.md linked) and how it fits the framework. The generated "How it is checked" and
  "History" sections keep their markers. Guarded by `tests/test_readme.py` (in the Server API check):
  template sections in order, markers in place, roadmap linked, each page title present in both the
  README and index.html, no file names in "What it does", every path named in backticks (also inside
  commands) is kept in Git, and CLAUDE.md names every test file. Review minor points fixed: CLAUDE.md
  test list, folder names in plain words, stricter path test.

## Next

- F9 review note: the README says a click on the tray icon opens the window; on a Mac it opens the menu.
- F8 review notes: on a Mac a Dock-icon click while the window is hidden probably does nothing (RunEvent::Reopen is not
  handled; first thing to try on a real Mac); checks/smoke.py, like app_server.py, never reads the core's stderr.
- F7 review notes: the Installer check reads build output outside Git (fails on a fresh clone until build.py ran); the
  desktop-icon hook puts the icon back on every upgrade; the start-menu capture (0.1.0) still shows the scrollbar fixed
  in 0.1.1; 0.1.2 (window lifted to the front when asked) is built but not installed.
- F6 review notes: clicking a notification works while the app runs (not from Action Center later, and the installed
  app's own notification id comes with F7's Start-menu entry); Mac notifications have no click route; a project whose
  phase turns waiting for a question while an already-announced draft is open raises no second decision.
- F5 review notes: choosing a workspace in the tray changes it on the core and the page follows on its next poll
  (F6's open-from-notification route will reload the page instead); the login check would misjudge "off by default" if
  an installed release later keeps its own Run entry under the same name.
- F4 review notes, for the human to decide: the welcome text says a workspace holds both
  framework and projects although only projects is required; unit-test cores read %TEMP%/settings.json if one exists;
  the rail sub-line and long workspace names are cut off at 1440 px.
- F2 review notes, for the human to decide: `ChangeMapApiTest.test_cached_unless_fresh` commits to the shared
  scheduler repo (its class's tests now depend on each other); `tests/test_core_only.py` counts a Rust test twice if
  a file names it twice (test_api: 149 counted, 139 without repeats, baseline 110); `checks/app_server.py` never reads
  the core's output after its first line (would stall if the core ever logged every request).
- Desktop app, next feature F10: retire the browser version (server.py, dashboard/, Open Dashboard.command; workspace README and framework/REFERENCE.md point to the app; parity check removed).
- GitHub warns that actions/checkout@v4, setup-python@v5 and upload-artifact@v4 still target Node.js 20 (forced to 24); newer major versions would silence it. F1 review notes for later: the no-git scan matches only `Command::new("git")`;
  broken UTF-8 in a record is read
  with replacement characters (server.py answered 500); the timestamp parser copies `fromisoformat` by hand.
- Colour-blind mode review notes, for the human to decide: (1) the eye button narrows the rail's brand block,
  so "Agent Control Room" wraps onto three lines and the sub-line is cut ("9 projects in this wo…"), also with
  the mode off; (2) in the mode, `--accent` (teal, used for "needs you") becomes pale grey under deuteranopia and sits
  near the planning grey, and the distance test does not cover `--accent`; (3) the deuteranopia screenshots are saved,
  not checked. Possible follow-ups: compact the brand block, give the accent its own colour-blind value in the distance test,
  hatch the failing bars in the mode as a cue that does not depend on colour.
Roadmap items 1 to 8 are all done; no roadmap item is left.

- Time estimate: the rail's progress bar for a working project could show the same striped band.
- The estimate is cached 15 s while "started N min ago" uses the page clock; fine for now, but a long-cached
  estimate would drift slightly from the elapsed time.

- Show a Git summary (unsent versions, behind) in the project list.

- Phone project row: compute "is the open chip hidden" from the visible area, and skip the
  delayed scroll after tapping a chip; add a check for the scroll behaviour.

## Known issues

- The render check uses the real clock, so data-pipeline's running task is now over 1000 hours long and the
  timeline's hour axis under it crowds its labels into one another (seen before and after F2; the timeline check
  pins the clock and does not see it).
- Redesign: the first-screen fit is checked on the fixtures. A real project with long texts can still grow row 2
  (step texts and test names are cut to one line, at most 5 tests show, but a "gone quiet" note or an opened fold
  makes a panel taller) and push row 3 partly below 900 px.
- Redesign: the change map preview gets only the height row 3 leaves (about 70 px when the timeline has one task); projects
  with many files get small tiles, and there is no larger view on tap (DESIGN.md suggests panels below the first
  screen may open wider). `tests/test_colours.py` scans the style block only (not inline styles or named colours). The "what to do" card for several
  unfinished fixes will make the hero row taller than one screen allows.
- Redesign follow-ups (second review, small): `tests/test_colours.py` skips every rule starting with `:root` (also
  `:root:not(...) .map-tile`), misses named colours and colours in inline styles from JavaScript; the zero-review
  wording ("No review has happened yet") is not asserted by a check; `check_git` runs in dark only, on three fixtures.
- Redesign: the track record panel hides each number's one-line explanation on wide screens (it is in the tooltip,
  in the workspace view and on phones), following the mockup.

- The render check needs Playwright installed into `.venv` once (see CLAUDE.md).
- The earlier note about `scheduler` scrolling sideways on phones no longer applies; the render check measures 0 px.
- Agent notes are reworded for framework terms and files only; the project's own file names (e.g. `train.py`) and jargon still appear as written.
- Phone project row: the fade on the right is always on (also dims the last chip when fully
  scrolled); even the five fixtures now need a swipe; tapping a chip past the first screen can
  cause a small delayed scroll; a chip hidden off the left edge is not brought back. No check
  covers the scroll code.
- Rewording covers a fixed list of framework terms: other draft ids (draft-2) and commands that
  contain aaf.py ("python3 the framework tool check ...") read awkwardly. The agent-wording check
  uses one note on one fixture at desktop size.
- No fixture is stuck below the attempt limit, so that wording of the stuck card is not exercised.
- Activity feed: Claude Code has no event at the moment of approval, so a long command the human already
  approved still shows "Needs you in Claude Code" until it finishes (`done`) or the next step starts.
- Activity feed: two permission prompts at once (parallel tool calls) are resolved together by the first
  `done`; an id-less wait is resolved with the waits that have an id. The two copies of one prompt are merged
  only when adjacent in the log (a parallel agent's step between them leaves two waits; after a refusal the
  id-less copy then waits for the main agent's next step or a reply), and the merge does not compare agents.
  No test has two agents waiting at once or a SubagentStop closing a subagent's wait.
- `checks/activity.py` does not pin the server's clock, so its notes-app screenshot shows an odd estimate
  ("about 1 minute to 59 hours left"); `checks/estimate.py` covers the estimate with a pinned clock.
- Activity feed: on finished, stuck, waiting and idle projects the "N min ago" texts update only
  when data changes (they could be updated in place without a full redraw).
- Activity feed: the longer "stuck · Claude Code is waiting" flag is checked at desktop width only;
  the decision-waiting case with a waiting step has no own assertion (same code path).
- Task timeline: the reason for a pause (stuck / waiting / finished) is read from the events sent
  with the stats; for tasks older than the newest 12 those events are not sent, so the pause says
  "No work was recorded". aaf.py's stats do not record intermediate outcomes per task.
- Task timeline: the end mark after each bar (✓ / ! / ✕) is not asserted by the check; attempt numbers
  above a bar overlap when a very long running stage squeezes the early ones; keyboard focus on a
  segment is lost on the live redraw (every 5 s, full page every 30 s). A fix was tried (draft fix-2,
  4 attempts) and discarded: restoring focus before the Git section is drawn made the page jump up on
  every full redraw. Notes for a next try are in state/drafts-notes.md (restore focus after the Git
  section, or keep scrollY across the redraw; test on the Git workspace).
- Task timeline: the number beside a bar is working time (pauses left out), not start-to-end; the
  pause is named in the row header (see decision).
- Task timeline: a stats run that keeps failing is retried on every poll (no wait between tries);
  each try can take up to 20 s. Not seen in practice.
- Task timeline: `checks/render.py` does not pin the clock, so the running fixtures' bars in
  `plots/render-*.png` grow to the real current time (honest, but they look stretched).
- Change map: in the plain fixtures (no framework tool) it shows "not available" while the Git section
  is hidden entirely; only the check's temporary Git workspace shows a real map.
- Change map: `aaf.py git files` counts at most the last 500 commits, so very old projects undercount
  (files untouched in that window are grey, "no change in the history read").
- Change map: tiny files all get the same minimum area (0.4% of the total), so a folder of many small
  files becomes a grid of equal tiles; with real data some tiles are only 6-10 px wide on a phone; only
  the top-level folder groups tiles, so deep paths get long, cut-off labels; the "no change" grey and the
  lightest blue are close in light mode; a failed read shows the raw error text; the background redraws
  (data refresh, resize) do not keep keyboard focus, only a tap does.
- Change map: check_keyboard's "page does not move" part uses a tile fully on screen, so it would not
  catch a missing preventScroll; a case with a partly visible tile would.
- Track record: themes come from keywords in one-line review summaries, so a summary in other words lands
  in "Other" (shown with its text); a summary naming two problems counts in both themes (the page says so). The review history
  is not linked to tasks, so the tap detail matches rejections to a task by time.
- Track record: the attempts chart shows the newest 30 tasks; the workspace view fetches `/api/record` every
  2.5 s (cheap: task stats are cached per project, review histories are re-read).
- Track record, All projects: the mixed case (a reason covered by one project's definition of done but not
  another's, "For X: <advice>") has no fixture or check; the overlap note has no screenshot; a covered reason
  names the project twice ("…of api-client already asks… Seen in api-client.").
- README: `tests/test_readme.py` checks paths in backticks only, not Markdown link targets (the link to the
  workspace README is unchecked; ROADMAP.md has its own test). The Git bullet says "hidden when the workspace
  has no framework tool", which a newcomer may not follow (from the second README review, not yet fixed).
- Tests panel times: `took()` in `checks/layout.py` copies the page's rounding (Python rounds exact halves
  differently, e.g. 12.5 s); the expected strings are not written by hand; tests are matched by name only
  loosely; 3600 s reads "60 min", not "1 h".
- `checks/render.py` lists the fixture folder raw (a stray `.DS_Store` would be treated as a project).

## Roadmap

Eight items, all built, one `/task` each: see `ROADMAP.md` for the order, the data sources and the paste-ready task texts. Mark each item done there when finished.
