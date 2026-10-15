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

All four roadmap items are done.

- Show a Git summary (unsent versions, behind) in the project list.

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
- Activity feed: `framework/hooks/activity.py` logs nothing after a permission is granted (no
  PostToolUse event), so a long command the human already approved keeps showing "Needs you in
  Claude Code" until the next step. Needs a hook change outside this project.
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
- `checks/render.py` lists the fixture folder raw (a stray `.DS_Store` would be treated as a project).

## Roadmap

Four features are planned and must all be built, one `/task` each: see `ROADMAP.md` for the order, the data sources and the paste-ready task texts. Mark each item done there when finished.
