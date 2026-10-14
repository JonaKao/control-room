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
  read from the end of the file; `/api/projects` carries each project's newest step.
  `/api/project` also carries `tasks`: the task timeline, i.e. `task_stats()` from `framework/aaf.py`
  (what `aaf.py stats <name>` prints), run in a subprocess on the project folder with the served
  workspace's aaf.py (or this workspace's, for a workspace without one, like the fixtures), cached
  until `state/events.jsonl` changes (a failed run is not cached), plus the events of the shown tasks for the segment details.
- **Git is the one exception to read-only.** Push and Pull run
  `<workspace>/framework/aaf.py git push|pull <name>`, never `git` directly. Writes are
  accepted only from the page itself: the request must come from this machine, carry the
  header `X-AAF-Request: control-room`, use a localhost `Host`, and any `Origin` must be
  this server. Pull is refused (409) while the project's agent is planning, implementing,
  checking, reviewing or fixing.
- `index.html`: the whole front end in one file (HTML, CSS, vanilla JS). It polls the
  API every 2.5 s and re-renders only when the data changed.
- The data model is defined by `framework/aaf.py` (status phases, checks.json,
  check_history.jsonl, review.json, decisions.md, progress.md, events.jsonl, drafts).
  Read it before changing what the page expects.

## How to run

From the workspace root: `python3 dashboard/server.py` (a shim that starts this one),
or double-click `Open Dashboard.command`. Then http://localhost:8765.
To view the fixtures: `python3 projects/control-room/server.py --root projects/control-room/fixtures/workspace --port 8770`.

## How to check

`python3 framework/aaf.py check control-room` runs:
1. **Server API**: unit tests against the fixture workspace (`tests/test_api.py`) and the
   Git endpoints against a temporary workspace with real repositories (`tests/test_git.py`)
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

The render check needs Playwright once, installed into a local `.venv` in this folder:

```
cd projects/control-room
python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
```

**Always open the screenshots in `plots/` with the Read tool after a visual change.**
Passing the checks only proves nothing crashed; the screenshots show whether the page
is actually clear.

## Fixtures

`fixtures/workspace/projects/` holds six projects, one per situation the page must
handle: `image-classifier` (running, failing a check), `parser` (waiting for a decision
on a draft), `example-done` (finished, with a plot and reviewer steps in its activity log),
`scheduler` (stuck), `brand-new` (nothing run yet, no activity log) and `web-scraper`
(mid-task, Claude Code waiting for permission). `state/activity.jsonl` in a fixture is
the live feed's data; its timestamps are fixed, so `checks/activity.py` pins the clock.
`state/events.jsonl` drives the task timeline: `example-done` has four tasks (finished first try,
stuck, stuck then resumed and finished, finished with a polish step), `image-classifier` a finished
and a running task, `parser` one that waits for a decision, `scheduler` one stuck after 8 attempts. If you add a new kind of state, add a fixture for it.

Git data is never stored in the fixtures. `checks/git_workspace.py` copies the fixtures
and `framework/aaf.py` into a temporary folder at test time, turns some projects into
repositories and adds a bare repository standing in for GitHub. aaf.py treats the folder it
sits in as the workspace, so this needs no changes to aaf.py.

## Conventions

- One file for the front end; no build step, no npm, no framework.
- External resources: only Google Fonts, and the page must still work without them.
- Colours as CSS variables on `:root`, with a dark theme.
- Plain language for people who don't know the code: say what is happening and why
  it matters, not internal names.

## Do not touch

- `server.py` must not write project files itself and must keep rejecting path traversal.
  Its only change to a project is Git push/pull through `aaf.py`, behind the page-only checks.
  Never call `git` from the server.
- `framework/aaf.py` is outside this project; ask before changing the data model.
