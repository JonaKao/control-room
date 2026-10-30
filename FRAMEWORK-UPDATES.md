# Framework updates for the control room

Changes made to the framework (outside this project) that the page can now use.
Newest first. When a task has used an update, note it under "Used by".

## 2026-10-21

1. **Tokens per task.** `aaf.py stats` now gives every task a `tokens` field
   (`input`, `output`, `cache_read`, `cache_write`, or `null` when nothing was
   recorded) and the summary `tokens_output` and `tokens_input_total`. Recorded by the
   activity hook at the end of each turn (`state/usage.jsonl`, cumulative per session).
   Only tasks run after this update have numbers. Good for the track record and timeline.
2. **Feature list.** Projects can have `features.json` (`aaf.py feature add|list|next|pass|fail`):
   `features[]` with `id`, `title`, `criteria`, `spec`, `passes`, `passed_at`, `evidence`.
   A "features passing" progress (e.g. 7 of 12) would fit the hero or the rail.
3. **New activity kind `feature`** in `state/events.jsonl` (feature added, passes,
   fails again), and **new phase meaning**: `waiting` with a note starting "Question:"
   means the agent asked the human something in Claude Code.
4. **Review findings can be `note`** (style or ideas, never auto-fixed) besides blocker,
   major and minor.

Used by: (not yet)

## 2026-10-19

1. **Per-commit "on GitHub" flag.** `aaf.py git info` now gives every commit a
   `pushed` field: `true` if GitHub has it (reachable from the upstream branch, as of
   the last fetch or push), `false` if it exists only on this Mac, `null` when the
   project has no upstream. Correct for merges and long histories. Replaces the
   "newest `ahead` commits" guess in the Git timeline.
2. **Activity hook: the "Needs you" gap is closed.** New record kinds in
   `state/activity.jsonl`, and every tool step now carries a `tool_use_id`:
   - `waiting` is now also written by a PermissionRequest hook, with the
     `tool_use_id` and the step it is about in `detail`.
   - `done` (with `quiet: true`) when a step finished. A `done` for the same
     `tool_use_id` as a `waiting` means the permission was granted and the step ran.
     Not a step of its own: use it to resolve waits, don't list it in the feed.
   - `error` when a step failed (`detail` holds the error).
   - `you` when the human sent a message in Claude Code: resolves "waiting for your reply".
   Claude Code has no event at the moment of approval, so a long approved command
   resolves when it finishes (`done`) or when the next step starts.
3. **Test durations exist.** `state/checks.json` has `duration_s` for every check, and
   always has. The tests panel can show per-test times as in the mockup.

Used by: control-room roadmap item 8 (2026-10-19). 1: the Git timeline's dashed "not on GitHub
yet" ring now comes from each commit's `pushed` (`false` only; `null` draws no ring). 2: the server
(`activity_steps` in server.py) leaves quiet records out of the feed, folds Claude Code's id-less
notification about a permission prompt into the wait logged with its `tool_use_id`, and marks a wait
`resolved` (by `done`/`error` for the same id, `you`, or the next step); the page shows it calmly
("You gave permission", "Asked for your reply; you answered") and lists `error` (red, with what went
wrong) and `you` records as steps. 3: the tests panel shows each test's `duration_s`.
