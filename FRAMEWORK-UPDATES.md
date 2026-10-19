# Framework updates for the control room

Changes made to the framework (outside this project) that the page can now use.
Newest first. When a task has used an update, note it under "Used by".

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

Used by: (not yet)
