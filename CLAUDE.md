# control-room

The Agent Control Room: the live dashboard for every project in this workspace.

## Purpose

Show, at a glance, what each project's agent is doing and whether the work is sound:
the current task, where the agent is in its loop, check results, the independent
review, drafts waiting for a decision, plots, decisions and progress. The audience
includes people who do not know the code behind it.

## How it works

- `server.py`: a small standard-library HTTP server. It reads files from
  `<workspace>/projects/*/state/` and `*/plots/` and never writes them itself. Endpoints:
  `/` (the page), `/api/projects`, `/api/project?name=`, `/plot?project=&file=`,
  `/api/git?name=[&fresh=1]` (runs `framework/aaf.py git info <name> --fetch`, cached 15 s),
  `/api/files?name=[&fresh=1]` (the change map: `framework/aaf.py git files <name>`, cached 30 s,
  dropped after Push/Pull),
  and `POST /api/git/push|pull` with `{"name": ...}`. `/api/project` also carries the newest
  30 steps of `state/activity.jsonl` (the live feed, written by `framework/hooks/activity.py`),
  read from the end of the file; `/api/projects` carries each project's newest step, `trend` (share of
  tests passing in each of the last 12 runs, for the rail's tiny line) and `plan` (`state/plan.json`:
  steps done, total, the current step and every step's text; `null` without a plan).
  `/api/project` also carries `tasks`: the task timeline, i.e. `task_stats()` from `framework/aaf.py`
  (what `aaf.py stats <name>` prints), run in a subprocess on the project folder with the served
  workspace's aaf.py (or this workspace's, for a workspace without one, like the fixtures), cached
  until `state/events.jsonl` changes (a failed run is not cached), plus the events of the shown tasks for the segment details.
  `/api/project` also carries `record`: `state/review_history.jsonl` and the failed reviews grouped by
  theme (`REASONS` in server.py: keywords in the one-line summary), each matched to the project's
  `DONE.md` item that covers it. `/api/record` is the workspace view ("All projects"): every project's
  task_stats summary and tasks (from the same cache) and the reasons across all projects.
- **Git is the one exception to read-only.** Push and Pull run
  `<workspace>/framework/aaf.py git push|pull <name>`, never `git` directly. Writes are
  accepted only from the page itself: the request must come from this machine, carry the
  header `X-AAF-Request: control-room`, use a localhost `Host`, and any `Origin` must be
  this server. Pull is refused (409) while the project's agent is planning, implementing,
  checking, reviewing or fixing.
- `index.html`: the whole front end in one file (HTML, CSS, vanilla JS). It polls the
  API every 2.5 s and re-renders only when the data changed. Layout and look follow the approved
  design in `design/DESIGN.md` (reference: `design/mockup.html`, `design/mockup-dark.png`): a left
  rail with four workspace numbers (`/api/record` gives the first-try rate) and a tiny picture per
  project; a full-width hero (its right half, `[data-slot=estimate]`, is "How far along", reserved
  for the time estimate, and gives way to the "what to do" card when the human is needed); then a
  12-column grid from 1200 px: step by step (5), tests (3), track record (4), where the time went
  (8), where the agent works (4); Git, pictures and more detail below. Under 1200 px one column.
- The data model is defined by `framework/aaf.py` (status phases, checks.json,
  check_history.jsonl, review.json, decisions.md, progress.md, events.jsonl, drafts).
  Read it before changing what the page expects.

## How to run

From the workspace root: `python3 dashboard/server.py` (a shim that starts this one),
or double-click `Open Dashboard.command`. Then http://localhost:8765.
To view the fixtures: `python3 projects/control-room/server.py --root projects/control-room/fixtures/workspace --port 8770`.

## How to check

`python3 framework/aaf.py check control-room` runs:
1. **Server API**: unit tests against the fixture workspace (`tests/test_api.py`), the
   Git endpoints against a temporary workspace with real repositories (`tests/test_git.py`),
   that each test file runs fully on its own (`tests/test_layout.py`), that built roadmap items
   stay marked done (`tests/test_roadmap.py`) and that `README.md` follows the template, names
   every part of the page and only points to files that exist (`tests/test_readme.py`), and that every
   colour in the page's styles comes from a token (`tests/test_colours.py`)
2. **Page renders in every state**: `checks/render.py` opens every fixture project in a
   headless browser (desktop light, desktop dark, phone), fails on JavaScript errors or
   sideways scrolling, and writes screenshots to `plots/render-*.png`.
3. **Understandable at a glance**: `checks/glance.py` (summary first, plain words, detail on demand).
4. **Git section works**: `checks/git_section.py` builds a temporary workspace with real
   repositories, then checks the timeline colours, sync picture, repo link, Push and Pull,
   and saves `plots/render-git-*.png`.
5. **Live activity feed**: `checks/activity.py` pins the browser clock and checks the current
   step, the recent history, reviewer marks, the "waiting for you in Claude Code" state and the
   "gone quiet" notice; it saves `plots/render-activity-*.png`.
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

`fixtures/workspace/projects/` holds seven projects, one per situation the page must
handle: `api-client` (finished, a long track record: nine tasks, six rejected reviews with repeated
reasons, a fix set aside, one stuck episode), `image-classifier` (running, failing a check, a plan
with 2 of 5 steps done), `parser` (waiting for a decision
on a draft), `example-done` (finished, with a plot and reviewer steps in its activity log),
`scheduler` (stuck), `brand-new` (nothing run yet, no activity log) and `web-scraper`
(mid-task, Claude Code waiting for permission). `state/activity.jsonl` in a fixture is
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

- `server.py` must not write project files itself and must keep rejecting path traversal.
  Its only change to a project is Git push/pull through `aaf.py`, behind the page-only checks.
  Never call `git` from the server.
- `framework/aaf.py` is outside this project; ask before changing the data model.
