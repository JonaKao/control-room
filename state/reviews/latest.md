# Review: F1 Rust core gives the same answers as server.py (iteration 2)

VERDICT: PASS
SUMMARY: F1 meets the spec; both review-1 fixes are in place; 13/13 checks pass (cargo test 45, parity.py).

## Findings
- [note] The no-git scan only matches Command::new("git"/"git.exe"); git started another way would not be caught (none exists today).
- [note] plain_file_name refuses drive names (C:probe.png); the one recorded difference from server.py, asserted in parity.py.
- [note] README does not yet mention app/, control-room serve, or that the checks need Rust (feature 9).
- [note] Still open from review 1: broken UTF-8 read with replacement characters; parse_iso is a hand-written fromisoformat.
