VERDICT: PASS
SUMMARY: The change map meets the task. All 7 checks pass, including the new "Change map" check; no existing check or test was weakened. Findings are minor robustness/readability issues seen with real data.

FINDINGS
- [minor] server.py git_files + index.html mapShell: if `aaf.py git files` fails or times out, the server returns {available: true, repo: false, error}; the page ignores error and says "This project is not saved with Git yet", which is false for a repository. Not covered by a test.
- [minor] index.html mapLayout (floor = total * 0.004): every file below 0.4% of the total gets the same area; on the real control-room repo the fixtures/ group becomes a grid of identical tiles. Disclosed in decisions.md; the area test only looks at tiles >= 2500 px².
- [minor] index.html renderMapSlot: with real data at phone width some tiles are very thin (6.8 px, 10 px), hard to tap; the check only requires 4 px.
- [minor] index.html: grouping by top-level folder only, so deep files get long truncated labels; on the phone the "config/" label covers most of its only tile.
- [minor] index.html mapStep: a file with 0 counted commits (older than aaf.py's 500-commit limit) gets class s0, which has no legend entry.
- [minor] index.html: tapping a tile re-renders the whole map, so keyboard focus is lost after each tap.
- [minor] Plain fixtures: the map shows "not available" while the Git section is hidden entirely (listed in progress.md).

DONE.md: every item met (7/7 checks, nothing weakened, covered by checks/change_map.py and ChangeMapApiTest, progress.md updated, screenshots inspected, plain language, server read-only, traversal rejected).
