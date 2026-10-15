# Review: control-room README, follow-up fixes

VERDICT: PASS (blockers: 0, majors: 0, minors: 2)

SUMMARY: The three earlier minor findings are fixed (CLAUDE.md test list, plain words instead of folder names in "What it does", path test now reads paths inside commands and counts only files kept in Git). All 8 checks pass when run independently; tests.test_readme 13 OK.

## Findings
- [minor] tests/test_readme.py: named_paths only looks at backtick spans; Markdown link targets such as [Agentic AI Framework](../../README.md) are not checked for existence (ROADMAP.md has its own test).
- [minor] README.md, Git section bullet: "Hidden when the workspace has no framework tool" — "framework tool" is unclear to a first-time reader.

## DONE.md
All items met: checks pass, nothing weakened, success covered by tests/test_readme.py, progress.md updated, screenshots regenerated and render-example-done-phone.png inspected (page code unchanged), server unchanged.
