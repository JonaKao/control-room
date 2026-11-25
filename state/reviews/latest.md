# Review: F6 Notifications

VERDICT: PASS
SUMMARY: F6 meets the spec; 16/16 checks pass; one real gap: a draft saved in a normal /fix run can send two "needs your decision" notifications.

## Findings
- [minor] app/src/watch.rs changes(): in /fix, `aaf.py draft save` runs first and `status --phase waiting` only after all issues were tried (usually much later than one 5 s look). The new draft raises ("decision", "draft:fix-k"); a later look sees the phase become waiting with drafts and raises ("decision", "phase:<updated>") with another key: two notifications for one draft. Suggested: skip the phase event when every current draft already raised a draft event.
- [note] checks/notifications.py writes the draft and the status one after the other while serve looks every 5 s; a look in between could make the check flaky (6 events).
- [note] The click route only works while the app runs and the toast belongs to it; Action Center clicks later, or an installed build without registered app id (F7), are not covered; Mac has no click route (recorded).
- [note] A draft meta.json without "id" uses the whole meta as key; rewriting it would raise a new decision.
- [note] Choosing a workspace in the tray now reloads the window and clears the remembered project (intended, in progress.md).
