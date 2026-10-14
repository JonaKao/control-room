# Control room roadmap

Four features, agreed on 2026-10-14. Each one is its own `/task`, in this order. All four
are to be built. When one is finished, mark it here (Status column), so the next session
knows where to continue.

| # | Feature | Answers the question | Data source (already provided by the framework) | Status |
|---|---|---|---|---|
| 1 | Live activity feed | What is the agent doing right now? | `state/activity.jsonl`, written by `framework/hooks/activity.py` | Done (2026-10-14) |
| 2 | Task timeline | Where did the time go? | `python3 framework/aaf.py stats <project>` → `tasks[].phases` | Not started |
| 3 | Change map | Where in the code does the agent work? | `python3 framework/aaf.py git files <project>` | Not started |
| 4 | Track record | How well is the agent doing over time? | `python3 framework/aaf.py stats <project>` → `summary`, plus `state/review_history.jsonl` | Not started |

Shared requirements for all four: plain language, as visual as possible, calm and
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
