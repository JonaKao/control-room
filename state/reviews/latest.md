VERDICT: PASS
SUMMARY: The time estimate meets Roadmap 7: a range with a striped band, "step N of M", time left as a range, a plain "based on" sentence with the task count, "not enough history yet" when there is no range, and how often estimates held in the hero and the track record. Fixtures cover the four scenarios, a new check covers it, and all 10 checks pass when run independently.

FINDINGS
- [minor] index.html:1339 — The "not enough history yet" text says "only the plan shows how far along it is" even when there is no plan (first-run fixture). The "3" is hard-coded (matches aaf.MIN_HISTORY today).
- [minor] index.html:1340 — The plan-based sentence says "from 14 past tasks from all projects" ("from" appears twice).
- [minor] index.html:1346 — The hero's "estimates held 7 of 10 times" covers all projects, but only the tooltip says so.
- [minor] fixtures/data-pipeline — "longer than all but one" rather than literally "longer than any". It reaches the same aaf branch and is documented.
- [minor] server.py:estimate — A failed run is not cached, so a project whose estimate always fails starts a subprocess on every poll.

DONE.md: all items met (progress.md updated by the implementer at the end).
