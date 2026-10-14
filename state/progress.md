# Progress

## Current state

- The dashboard lives in this project; `dashboard/server.py` is a shim that starts `server.py` here.
- **Redesigned layout (2026-10-14)**, built for people who don't know the code. Top to bottom:
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

## Next

- Show a Git summary (unsent versions, behind) in the project list.

- Possibly a per-task timeline (when each attempt started, how long each took).
- Phone project row: compute "is the open chip hidden" from the visible area, and skip the
  delayed scroll after tapping a chip; add a check for the scroll behaviour.

## Known issues

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
- Git timeline: "not on GitHub yet" marks the newest `ahead` commits, which is only right for a straight
  history (merges, more than 40 commits). A real fix needs `aaf.py git info` to report a per-commit pushed flag,
  a change to the framework's data model; waiting for the human's go-ahead.
- `checks/render.py` lists the fixture folder raw (a stray `.DS_Store` would be treated as a project).
