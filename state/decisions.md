# Decisions

Newest last. Add entries with `python3 framework/aaf.py decide <project> "Title" "Rationale"`.

## 2026-10-14: Dashboard moved into its own project

So agents can improve it with /task like any other code. dashboard/server.py stays as a shim, so existing launch instructions keep working.

## 2026-10-14: Visual changes are checked with a headless browser

checks/render.py renders five fixture states in light, dark and phone views and saves screenshots for the agent to inspect. Rejected: only API tests, which cannot see layout problems.

## 2026-10-14: Glance test as a separate headless check

checks/glance.py turns the DONE.md items into testable markers: first section is the glance summary and fits the first screen (desktop and phone), says what the agent does and whether the human is needed (matched against each fixture), no file names or internal terms in it, a loop picture, an action section right after when needed, visuals for tests/attempts/history, decisions/progress/activity in closed details blocks. Rejected: folding it into render.py (keeps the crash check simple) and pixel/screenshot diffing (brittle). render.py now screenshots all five fixtures instead of two, so every state can be inspected; nothing it checked was removed.

## 2026-10-14: Glance check measures visibility with checkVisibility()

The first version counted <pre> blocks with offsetParent !== null as visible. Chromium keeps content of a closed <details> laid out, so offsetParent is set even when nothing is shown: the check flagged hidden test output as visible. checkVisibility() reports what the user actually sees. This makes the check accurate, not looser; it still fails if raw output is shown on load. Note: render.py's all-fixtures screenshot change was made before the before-redesign snapshot was taken.

## 2026-10-14: Glance check covers every fixture folder

checks/glance.py now fails if a fixture folder is not listed in NEEDS (or NEEDS names a missing one), so a new fixture can't be skipped silently. Only real folders count (dotfiles like .DS_Store ignored). Whether to expect test/history visuals is read from the fixture's own state files instead of hand-kept name sets; the expected 'needs you' count is derived from NEEDS. Reviewer PASS. render.py still lists the folder raw; left as is.

## 2026-10-14: Stuck projects show what was tried and why it stopped

Loop steps before Stuck are drawn grey ('tried') instead of unreached or green: the agent went through them, none led to a pass. The card says 'used all N attempts' when iteration >= max_iterations, otherwise the repeat-failure reason (the framework only sets stuck below the limit after the same failure 3 times). The last step's hint names the outcome. First review FAILed only because progress.md was stale; fixed in iteration 2 rather than rolled back, since the code was verified correct. Reviewer PASS.

## 2026-10-14: Agent-written text is reworded in plain words

A shared plain() rewords the task, the agent's notes and the activity log: framework files (progress.md, decisions.md, DONE.md, aaf.py, status.json, ...) become 'the progress note', 'the decision log', ...; iteration -> attempt; checks -> tests (noun only, the verb 'check' stays); draft fix-N -> 'unfinished fix N'; minor findings -> small review points. The project's own file names (train.py) are left as written: they are the user's vocabulary. Rejected: stripping file names (loses meaning). glance.py feeds a jargon note through the real page to guard it. Reviewer PASS (two rounds).

## 2026-10-14: Phone project list is one sideways-scrolling row

Wrapping chips pushed the summary off the first screen with many projects (967px with 35). Under 860px the list is now a single row that scrolls on its own with a fade on the right; the overview line ('2 need you') stays visible regardless. A refresh keeps the user's swipe position; the open chip is scrolled into view only on first load or project change, and only if off-screen. Rejected: a <select> dropdown (hides the coloured status dots) and collapsing the list (one more tap). glance.py checks 35 projects on phone. Reviewer PASS (two rounds).

## 2026-10-14: Git data and actions go through the served workspace's aaf.py

The server runs <workspace>/framework/aaf.py (git info --fetch, git push, git pull) with the current Python, never git itself; aaf.py derives its workspace from its own location, so tests build a temporary workspace with a copy of aaf.py, real repositories and a bare repo standing in for GitHub (checks/git_workspace.py). A workspace without aaf.py (the plain fixtures) reports Git as unavailable. Rejected: committing a .git into fixtures (asked against), and passing --root to aaf.py (would change the data model outside this project).

## 2026-10-14: Write requests only from the page itself

POST /api/git/push|pull is accepted only when the client is on this machine, the custom header X-AAF-Request: control-room is set (a cross-site page cannot send it without a CORS preflight, which the server never answers), the Host header is localhost/127.0.0.1 (DNS rebinding) and any Origin is this server. Pull is refused (409) while the project's agent is planning, implementing, checking, reviewing or fixing. Rejected: a token in the page (adds secrets handling for no gain on localhost) and allowing GET for actions.

## 2026-10-14: DONE.md: server read-only item reworded for Git

The task explicitly adds Push/Pull to the server and asks to update CLAUDE.md, which called it read-only. The DONE.md item 'The server still only reads files' could no longer hold, so it now reads: the server writes no project files itself (Git only through aaf.py, page-only requests) and still rejects path traversal. Everything else in that item (traversal tests) is unchanged; tests/test_git.py adds checks that the server never calls git and that writes from other origins/hosts or without the header are refused.

## 2026-10-14: Write requests refuse bad body lengths

do_POST accepts a Content-Length only if it is an integer in 0..4096; anything else gets 400 at once and the connection is closed. A negative length used to make rfile.read(-1) block the server thread. Reviewer PASS.

## 2026-10-14: Fixed: simultaneous Git info requests share one aaf.py git info --fetch

Per-project lock in git_info; cache entries carry started and finished stamps. The 15 s cache life counts from finished; any waiter reuses a run that started after it asked; a fresh request never reuses a run that started before it asked (so data from before a push is never shown as fresh). Rejected: a single start-time stamp (draft fix-2, first attempt), because a fetch slower than the cache life left an expired entry and the waiting requests then ran aaf.py one after another.

## 2026-10-14: Fixed: Review trailer read the same way everywhere

A shared reviewOf() in index.html trims and lowercases the Review trailer and returns pass, fail or nothing; commitState (colour) and commitDetail (words and icon) both use it. 'Review: PASS' was green in the timeline but 'did not approve' in the detail; unknown values like 'skipped' now show no review line instead of a wrong one. checks/git_section.py check_trailer_case tests PASS, ' Fail ' and 'skipped'. Reviewer PASS (second round; the first failed only because progress.md was not updated).

## 2026-10-14: Fixed: Git screenshots show one screen

checks/git_section.py scrolls the Git section into view on desktop as well as phone and saves one viewport-sized screenshot; check_screenshot_view fails if the saved PNG is not exactly the viewport size or the section's top is off screen. The full-page capture stitched the sticky project list into the middle of the image. Rejected: keeping full_page and hiding the rail (would show something a person never sees). Reviewer PASS.

## 2026-10-14: Fixed: Git API tests no longer depend on their order

Push, pull and phase-change tests moved to GitWriteTest with a fresh workspace per test; read and refused-write tests share one workspace in GitApiTest. GitTestOrderTest runs both classes in reverse method order. Before, the push and pull tests changed the shared workspace and the info tests passed only because of alphabetical order. Cost: the Server API check takes about 18 s instead of 7 s. Reviewer PASS.

## 2026-10-14: Activity feed: an idle prompt after a finished task does not need the human

framework/hooks/activity.py logs kind 'waiting' both for permission prompts and for Claude Code's idle 'waiting for your input' notice, which fires after every finished turn. Treating every latest 'waiting' entry as 'needs you' would flag every finished or idle project forever. Rule: a latest 'waiting' entry needs the human when it is a permission request, or when the project's stage is not finished/not started (the agent stopped mid-task for a reply). After a finished task, an idle prompt is shown calmly as 'idle in Claude Code, ready for a new task'. Rejected: flagging every 'waiting' entry (noise), ignoring the idle notice entirely (misses an agent that asked a question mid-task).

## 2026-10-14: Fixed: summary flag stays specific when quiet or stuck

A waiting step adds 'Claude Code is waiting' to a stuck or decision message instead of replacing it, and toneOf keeps stuck projects red. While the feed is quiet the calm flag says 'Probably nothing needs you, but it has been quiet for N min' instead of 'It will keep going on its own'. checks/activity.py covers both. Reviewer PASS.

## 2026-10-14: Fixed: every test file runs completely on its own

tests/test_api.py had ActivityTailTest after its __main__ block, so running the file directly skipped 3 tests. The block moved to the end; tests/test_layout.py fails if any test file defines a test class after its __main__ block. Reviewer PASS.

## 2026-10-14: Fixed: the page redraws on a timer only while a task runs

The 30 s time-based redraw (needed so 'gone quiet' appears without new data) now applies only to running stages; finished, stuck, waiting and idle projects redraw only when their data changes, so selected text is kept. Cost: 'N min ago' texts on those projects update only with new data, as before the feed. checks/activity.py asserts a finished project is not redrawn. Reviewer PASS.

## 2026-10-14: Task timeline: data from aaf.py task_stats, run against any project folder

The server runs the served workspace's framework/aaf.py (or, when that workspace has none, as with the plain fixtures, the aaf.py of the workspace the server lives in) in a subprocess and calls its task_stats(<project folder>), which is exactly what 'aaf.py stats <name>' prints. The CLI derives the project folder from its own location, so it cannot read the fixture workspace. Result cached per project until events.jsonl changes (size + mtime), so polling costs one stat() call. Rejected: re-implementing the event parsing in the server or page (two copies of the data model), and copying aaf.py into the fixtures (would also turn on the Git section in every render).

## 2026-10-14: Task timeline: bars on a shared working-time scale, pauses drawn as a short break

Each task's bar starts at the left and its length is its working time on one scale shared by all rows, so tasks can be compared; the start time is written on the row. An absolute calendar axis was rejected: tasks hours or days apart would shrink to slivers. Time between a stop (stuck or waiting) and a resume is not work; it is drawn as a fixed-width hatched break with its length in words, otherwise one overnight pause would flatten every other bar. The duration beside the bar is working time; the pause is named separately.

## 2026-10-15: Fixed: timeline events filtered by time, failed stats runs not cached

server.task_stats compared event timestamps as text, wrong when the log mixes time zone offsets; it now compares epoch seconds (_when), keeping events whose time cannot be read. A failed or timed-out aaf.py run was cached until events.jsonl changed; now only successful runs are cached. Tests: test_events_filtered_by_time_not_text, test_failed_run_is_not_cached (both fail on the old code). Not done: a short wait before retrying a failing run (kept as a known issue). Reviewer PASS.

## 2026-10-15: Change map: two-level squarified treemap, own endpoint, cached like Git info

GET /api/files?name= runs the served workspace's 'aaf.py git files <name>' and caches it 30 s per project (dropped after Push/Pull); the page loads it separately, like the Git section, so the 2.5 s project poll stays cheap. Layout: files grouped by their top-level folder (top-level files in one group), squarified so tiles stay close to square and readable; deeper folders show in the tile's label. Group names are drawn over the tiles instead of in a header strip, so tile area stays proportional to file size across groups. Colour: one blue ramp in five steps by number of saved versions that changed the file (1, 2, 3-4, 5-8, 9+), roughly logarithmic because a few files change far more often than the rest. Very small files get a minimum area so they can still be tapped. Rejected: nested treemap per folder level (labels unreadable at phone width), area from lines changed (the task asks for size).

## 2026-10-15: Change map: bookkeeping hidden by default

The task asks to offer hiding state/ and plots/ so the code stands out. Hidden is the default because the map's question is where the agent works in the code; the framework's own notes, test records and screenshots change on every task and would otherwise dominate the colours. One tap shows them; the choice is remembered in the browser. Rejected: showing everything by default (the code is drowned out in every project that uses the framework).

## 2026-10-15: Fixed: change map says when the history could not be read; legend for files with no counted change

A failed or timed-out 'aaf.py git files' was shown as 'not saved with Git yet'; the page now says the history could not be read and that it retries every minute (the server does not cache failures). Files with 0 counted commits (older than the 500 commits aaf.py reads) are grey and get a legend entry. checks/change_map.py check_odd_data covers both (verified by the reviewer to fail without the fix). Reviewer PASS.

## 2026-10-15: Fixed: change map keeps keyboard focus on a tapped tile

Tapping a tile redrew the map and dropped focus. renderMapSlot(path) now focuses the tapped tile with preventScroll, only after a tap and only once the map is fully drawn, so the background redraws never move focus or the page (the lesson from the discarded timeline draft fix-2). checks/change_map.py check_keyboard: Enter opens and a second Enter closes the detail, focus stays, page does not move; fails without the fix. Its scroll assertion would not catch a missing preventScroll (the tile is fully on screen); the reviewer probed partly visible tiles by hand. Reviewer PASS.
