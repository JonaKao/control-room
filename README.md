# control-room

The Agent Control Room: one web page that shows, live, what the coding agent in each
project of this workspace is doing and whether its work can be trusted.

## What it does

The [Agentic AI Framework](../../README.md) lets coding agents (Claude Code) work on
projects with little supervision: an agent plans a task, changes the code, runs the
project's tests, has an independent reviewer look at the result and repeats until the
project's definition of done holds. All of that is written to files in a records folder
inside each project. The control room reads those files and turns them into a page a person
can follow without knowing the code or the framework: what is happening now, whether
anything needs them, and how the work went.

On the left is the project list, grouped into "Needs you", "Working", "Finished" and
"Not started", with "All projects" on top. Picking a project shows, from top to bottom:

- **At a glance** (the summary): the project, a pill that says "Needs you" or "Nothing
  needs you", one plain sentence on what the agent is doing, the current task, the
  agent's latest note and a picture of its loop (Plan → Change → Test → Review →
  Finished, Your call or Stuck) with the number of attempts so far. A "Right now" line
  says what the agent's latest step was and how long ago. Someone who reads only this
  part knows what is going on and whether to act.
- **What to do** appears only when something needs you: unfinished fixes the agent set
  aside, each with its two choices (continue or discard) and the command to copy, or
  advice when the agent is stuck or waits for permission in Claude Code.
- **Step by step**: the live activity feed. The latest step in large type with an icon
  for its kind (reading, editing, testing, ...), the eight before it, and the rest of the
  recent steps behind a fold. Steps taken by the independent reviewer carry a "Reviewer"
  badge. When Claude Code waits for your reply it says so plainly; when a running task
  has sent no step for five minutes it says the feed has gone quiet.
- **Is the work sound?**: the latest test results (a ring with a tick or cross per test),
  the reviewer's verdict and how many attempts were used. Test output and the full review
  are one tap away.
- **Where the time went**: the task timeline. One bar per task, latest on top. Each bar is
  split into coloured segments for planning, making a change, testing, being reviewed and
  polishing (fixing the reviewer's small points afterwards), with
  marks where a new attempt began, a hatched break where the task stood still, the outcome
  at the end and the working time beside it. Tapping a segment tells what happened in it.
  A running task's bar grows while you watch.
- **Test runs over time**: one bar per test run, so a run of failures stands out.
- **Track record**: how well the agent does over time. Four numbers (tasks right the first
  time, reviews that said no, fixes set aside, times stuck), a chart of attempts per task,
  and "Why the review said no": the reviewer's rejections grouped by theme, most common
  first, each with a hint on what to sharpen in the project's instructions or definition
  of done. "All projects" in the list shows the same across the whole workspace.
- **Saved versions (Git)**: this computer ⇄ GitHub (versions to send, versions to get,
  unsaved files), Push and Pull buttons, a link to the repository, and a timeline of the
  saved versions coloured by whether tests passed and the review approved. Pull is refused
  while the agent is working. Hidden when the workspace has no framework tool.
- **Where the agent works**: the change map. Every file of the project as a tile, grouped
  by folder; a bigger tile is a bigger file, a darker blue one was changed more often.
  Tapping a tile shows its last change. The framework's own records (progress notes, test
  results, screenshots) are hidden unless you ask for them.
- **Pictures from the project**: plots the project produced, when there are any.
- **More detail**, folded away: the decision log, the agent's progress note and the full
  activity log.

The page updates itself every few seconds, works in light and dark mode and on a phone.

## How to run

From the workspace root:

```
python3 dashboard/server.py
```

then open http://localhost:8765. On a Mac you can instead double-click
`Open Dashboard.command`, which also opens the browser. `dashboard/server.py` is only a
shim that starts `server.py` in this folder, which takes `--port` (default 8765),
`--host` (default 127.0.0.1) and `--root` (the workspace to show).

To look at the made-up example projects instead of the real ones:

```
python3 projects/control-room/server.py --root projects/control-room/fixtures/workspace --port 8770
```

Nothing to install for the page itself: it needs only Python 3. The checks that open the
page in a browser need Playwright once:

```
cd projects/control-room
python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
```

## How it is built

- `server.py`: a small HTTP server using only Python's standard library. It reads each
  project's `state/` and `plots/` folders and answers the page's questions as JSON. It
  never writes project files and refuses paths outside the workspace. Derived data comes
  from the framework rather than being recomputed: the task timeline and track record
  from `framework/aaf.py stats`, the change map from `aaf.py git files`, the Git section
  from `aaf.py git info`; results are cached so polling stays cheap. The only thing it
  changes is Git, and only through `aaf.py git push|pull`, only for requests from the page
  itself on this machine.
- `index.html`: the whole page in one file (HTML, CSS and plain JavaScript, no build step,
  no libraries). It asks the server for fresh data every 2.5 seconds and redraws only what
  changed.
- `fixtures/`: a pretend workspace with seven projects, one for each situation the page
  must handle (running, stuck, waiting for a decision, waiting for permission, finished,
  never started, a long track record). Git repositories are never stored there; the checks
  build them in a temporary folder with `checks/git_workspace.py`.
- `tests/`: unit tests for the server's answers, its Git safety rules, and this README.
- `checks/`: scripts that open the page in a headless browser for every fixture (desktop
  light, desktop dark, phone), fail on errors or sideways scrolling, test each section's
  behaviour, and save screenshots to `plots/` for a person or agent to look at.
- `ROADMAP.md`: the four features planned on 2026-10-14 (activity feed, task timeline,
  change map, track record) and their status. See [ROADMAP.md](ROADMAP.md).

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
<!-- aaf:checks:end -->

## History

Finished tasks, newest first. Generated from the project's records on every commit.

<!-- aaf:history:start -->
- 2026-10-15: Write README.md for the control room from the template: what it is, each part of the page, how to start, how it is built, how it fits the framework (first try, review passed)
- 2026-10-15: Roadmap 4: add a track record (per-project and workspace view, common review-failure reasons) (2 attempts, review passed)
- 2026-10-15: Roadmap 3: add a change map (treemap of files from aaf.py git files) (first try, review passed)
- 2026-10-15: Roadmap 2: add a task timeline (per-task bars split into phases, from aaf.py stats) (first try, review passed)
- 2026-10-14: Roadmap 1: live activity feed from state/activity.jsonl (3 attempts, review passed)
- 2026-10-14: Add a visual Git section: commit timeline, sync state, repo link, Push/Pull buttons (3 attempts, review passed)
- 2026-10-14: Redesign the layout so a newcomer sees at a glance what the agent is doing and whether anything needs them (4 attempts, review passed)
<!-- aaf:history:end -->
