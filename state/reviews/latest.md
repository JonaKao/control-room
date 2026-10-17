# Review: follow-up fixes to the redesign (second round)

VERDICT: PASS (blockers: 0, majors: 0, minors: 5)

SUMMARY: All three fixes do what their issues ask (layout check on real Git data, no empty reasons fold, plot colours as tokens) and all 9 checks pass when run independently. The first round failed only because state/progress.md had not been updated for the fixes; now it is.

## Findings
- [minor] tests/test_colours.py skips every rule whose selector starts with :root, not only the token blocks.
- [minor] tests/test_colours.py does not see named colours or literals in inline styles built in JavaScript (none today).
- [minor] --plot-bg, --plot-ink and --backdrop are not in design/DESIGN.md.
- [minor] checks/track_record.py does not assert the separate "No review has happened yet." wording for zero reviews.
- [minor] check_git covers three fixtures in dark only.
