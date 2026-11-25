# Review: F4 Several workspaces (iteration 3)

VERDICT: PASS
SUMMARY: F4 meets the spec; 15/15 on the second full run (the first had a Windows file-write error in render.py that did not repeat); the page works on server.py again; README updated.

## Findings
- [note] checks/render.py: OSError [Errno 22] writing plots/render-brand-new-phone.png in one full run (file lock by indexer/antivirus?), not repeated.
- [note] check_folder accepts any folder with projects/ (decision recorded) while the welcome text says a workspace holds both folders.
- [note] POST /api/settings lets the page choose the executable run as Python (behind the write guard).
- [note] Test cores use std::env::temp_dir() as config folder and would read a settings.json there.
- [note] The native folder picker itself is not tested (button and can_pick are).
- [note] Rail subtitle and long workspace names are cut off at 1440 px.
