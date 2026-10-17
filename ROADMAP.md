# Control room roadmap

Features agreed on 2026-10-14, 2026-10-15 and 2026-10-17. Each one is its own `/task`, in this order. All
of them are to be built. When one is finished, mark it here (Status column), so the next session
knows where to continue.

| # | Feature | Answers the question | Data source (already provided by the framework) | Status |
|---|---|---|---|---|
| 1 | Live activity feed | What is the agent doing right now? | `state/activity.jsonl`, written by `framework/hooks/activity.py` | Done (2026-10-14) |
| 2 | Task timeline | Where did the time go? | `python3 framework/aaf.py stats <project>` → `tasks[].phases` | Done (2026-10-14) |
| 3 | Change map | Where in the code does the agent work? | `python3 framework/aaf.py git files <project>` | Done (2026-10-15) |
| 4 | Track record | How well is the agent doing over time? | `python3 framework/aaf.py stats <project>` → `summary`, plus `state/review_history.jsonl` | Done (2026-10-15) |
| 5 | README | What is this project, for someone new to it? | `template/README.md`; generated sections refreshed by `aaf.py git commit` | Done (2026-10-15) |
| 6 | Instrument-panel redesign | Does everything important fit on one laptop screen? | `design/DESIGN.md`, `design/mockup.html`, `design/mockup-dark.png` (approved 2026-10-17) | Done (2026-10-17) |
| 7 | Time estimate | How far along is the task, and how long is left? | `python3 framework/aaf.py estimate <project>`; plan steps in `state/plan.json`; accuracy in `aaf.py stats` → `estimate_accuracy` | Not started |

Shared requirements for all features: plain language, as visual as possible, calm and
consistent with the existing design, detail on demand. Each feature gets fixtures for
its data (including an empty state) and is covered by the render check. The server stays
read-only for this data; call `aaf.py` for derived data rather than re-implementing it,
and cache it like the Git info.

## Task texts (paste into Claude Code)

### 1. Live activity feed

```
/task control-room Roadmap 1: add a live activity feed. Read state/activity.jsonl (one JSON line per step, written by framework/hooks/activity.py: ts, kind, text, optional detail and subagent; kinds include read, edit, search, test, framework, command, agent, web, plan, waiting, turn). Show the current step prominently near the top and a short recent history beneath, with an icon per kind; mark steps taken by the reviewer subagent. When the latest entry has kind "waiting", make it unmistakable that the human is needed in Claude Code. If the phase is active but no step has arrived for several minutes, say the feed has gone quiet. Add fixtures with activity logs, including a waiting one. Mark roadmap item 1 done in ROADMAP.md.
```

### 2. Task timeline

```
/task control-room Roadmap 2: add a task timeline. Get the data from `python3 framework/aaf.py stats <project>` (tasks[] with start, end, outcome, attempts, phases[] of phase, iteration, start, end, duration_s). Draw each task as a horizontal bar on a time axis, split into its phases with one colour per phase, attempt boundaries marked, the outcome (done, waiting for a decision, stuck) at the end and the total duration beside it. Latest task on top; tapping a segment shows what happened in it. Running tasks grow live. Add fixtures with several tasks, including a stuck one and one that resumed after being stuck. Mark roadmap item 2 done in ROADMAP.md.
```

### 3. Change map

```
/task control-room Roadmap 3: add a change map. Get the data from `python3 framework/aaf.py git files <project>` (files[] with path, bytes, commits, lines_changed, last_changed, last_subject). Draw a treemap of the project's files grouped by folder: tile area from file size, colour from how often commits changed the file. Tapping a tile shows the file's last change and how many times it changed. Offer to hide framework bookkeeping (state/, plots/) so the code itself stands out. Handle projects that are not Git repositories yet with a clear empty state. Mark roadmap item 3 done in ROADMAP.md.
```

### 4. Track record

```
/task control-room Roadmap 4: add a track record. Use `python3 framework/aaf.py stats <project>` (summary: tasks, done, waiting, stuck, first_try, reviews, review_fails, drafts, times_stuck, median_attempts; tasks[] for trends) and state/review_history.jsonl for review summaries. Per project, show how often tasks pass on the first try, how often reviews reject work, attempts per task over time, and drafts and stuck episodes. Also add a workspace view across all projects. Purpose: help the human see where CLAUDE.md or DONE.md instructions need sharpening, so list the most common reasons reviews failed. Mark roadmap item 4 done in ROADMAP.md.
```

### 5. README

```
/task control-room Roadmap 5: create README.md for this project from template/README.md. Explain for someone who has never seen it what the control room is and what each part of the page shows (summary, step-by-step activity, task timeline, change map, track record, Git section), how to start it, how it is built (server, page, fixtures, checks) and how it fits into the Agentic AI Framework. Keep the generated sections with their markers. Link ROADMAP.md. Mark roadmap item 5 done in ROADMAP.md.
```

### 6. Instrument-panel redesign

```
/task control-room Roadmap 6: redesign the page to match the approved design in design/DESIGN.md, using design/mockup.html and design/mockup-dark.png as the reference. Instrument-panel layout: left rail with the workspace headline numbers and a tiny visual per project; a full-width hero (task, attempt, right now, loop stepper, with its right half reserved for the time estimate); then a 12-column grid of panels so that live steps, tests, track record, timeline and change map all fit on the first laptop screen; the rest below. Dark theme by default, light still available; one colour per phase used identically everywhere; the type and colour tokens from DESIGN.md. Keep every existing feature, the plain language and the phone layout. Compare your screenshots side by side with design/mockup-dark.png before calling it done, and add a check that the hero and the five main panels are all visible within the first 1440 x 900 screen. Mark roadmap item 6 done in ROADMAP.md.
```

### 7. Time estimate

The hero's right half ("How far along", `[data-slot=estimate]`) already shows the plan's steps; this item adds the range.

```
/task control-room Roadmap 7: show how far along a running task is and how long is left. Get the data from `python3 framework/aaf.py estimate <project>` (active, phase, elapsed_s, plan {steps, done, current}, progress_low/high as fractions, remaining_low_s/high_s, basis, history_tasks, history_scope, calibration {predictions_checked, coverage, width_scale}); cache it briefly like the Git info. Show it as a range, never a single number: a progress bar with a shaded band from progress_low to progress_high, "step 3 of 5" with the current step, and "about 20 to 45 minutes left". Say plainly what it is based on and how many past tasks, and say "not enough history yet" when the range is missing. In the track record, add how often past estimates held (calibration.coverage, with the number of predictions checked). Add fixtures for planning without history, mid-plan, in review, and a task running longer than any before. Put it in the hero's right half ("How far along"), as in design/mockup-dark.png. Mark roadmap item 7 done in ROADMAP.md.
```
