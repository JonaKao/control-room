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
