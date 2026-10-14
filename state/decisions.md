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
