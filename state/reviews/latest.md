# Review: F10 Browser version retired

VERDICT: PASS
SUMMARY: The browser version is removed, the workspace guides point to the app, the parity check's removal is recorded with its coverage kept elsewhere, DONE.md reworded; 17/17 checks pass.

## Findings
- [note] .claude/launch.json (untracked, machine-specific, not in the spec's list) still starts dashboard/server.py; left for the human.
- [note] The page's offline message names the Start menu and tray: wrong on a Mac and in serve mode.
- [note] test_readme's path-finder example no longer finds a bare file name containing a space (no kept file has one; recorded).
- [note] Parity's other coverage is real elsewhere: drive names (Rust tests, smoke.py), pull refusal and bad Content-Length (test_git.py, smoke.py), the no-git scan (test_git.py).
- [note] Rust comments and the README history still mention server.py (historical).
- [note] checks/__pycache__/parity.cpython-312.pyc left over (harmless).
