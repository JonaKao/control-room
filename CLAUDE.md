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
  and `POST /api/git/push|pull` with `{"name": ...}`.
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
