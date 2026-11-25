# Review: F8 Mac build on GitHub

VERDICT: PASS
SUMMARY: The workflow tests, builds, smoke-checks and uploads the .exe and .dmg on both runners; run 45626493353 green on both; 18/18 local checks; platform paths have Mac counterparts; unchecked Mac behaviour listed.

## Findings
- [note] No local check covers the green GitHub run; the evidence is gh run view (inherent).
- [note] On a Mac the tray click returns early and RunEvent::Reopen is not handled: a Dock-icon click with the window hidden probably does nothing (disclosed as untested).
- [note] checks/smoke.py pipes stderr without draining it (same as app_server.py).
- [note] Node 20 deprecation warning for checkout@v4, setup-python@v5, upload-artifact@v4 (recorded); the .dmg is arm64 only (said).
- [note] The 0.1.3 version bump, README, tests and progress were uncommitted at review time; the tested Rust and workflow code is unchanged since 119559a.
