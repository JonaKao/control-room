# control-room

The Agent Control Room: the live dashboard for every project in this workspace.

## Purpose

Show, at a glance, what each project's agent is doing and whether the work is sound:
the current task, where the agent is in its loop, check results, the independent
review, drafts waiting for a decision, plots, decisions and progress. The audience
includes people who do not know the code behind it.

## How it works

- `server.py`: a small standard-library HTTP server. It only reads files from
  `<workspace>/projects/*/state/` and `*/plots/`; it never writes. Endpoints:
  `/` (the page), `/api/projects`, `/api/project?name=`, `/plot?project=&file=`.
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
1. **Server API**: unit tests against the fixture workspace (`tests/test_api.py`)
2. **Page renders in every state**: `checks/render.py` opens every fixture project in a
   headless browser (desktop light, desktop dark, phone), fails on JavaScript errors or
   sideways scrolling, and writes screenshots to `plots/render-*.png`.

The render check needs Playwright once, installed into a local `.venv` in this folder:

```
cd projects/control-room
python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium
```

**Always open the screenshots in `plots/` with the Read tool after a visual change.**
Passing the checks only proves nothing crashed; the screenshots show whether the page
is actually clear.

## Fixtures

`fixtures/workspace/projects/` holds five projects, one per situation the page must
handle: `image-classifier` (running, failing a check), `parser` (waiting for a decision
on a draft), `example-done` (finished, with a plot), `scheduler` (stuck), `brand-new`
(nothing run yet). If you add a new kind of state, add a fixture for it.

## Conventions

- One file for the front end; no build step, no npm, no framework.
- External resources: only Google Fonts, and the page must still work without them.
- Colours as CSS variables on `:root`, with a dark theme.
- Plain language for people who don't know the code: say what is happening and why
  it matters, not internal names.

## Do not touch

- `server.py` must stay read-only towards projects and keep rejecting path traversal.
- `framework/aaf.py` is outside this project; ask before changing the data model.
