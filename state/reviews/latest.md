# Review: F5 Tray and background

VERDICT: PASS
SUMMARY: F5 meets every acceptance criterion; 15/15 checks pass; the desktop check drives tray, single instance and login; nothing weakened.

## Findings
- [note] tray_choice selects the workspace on the core only; the page notices on its next poll without afterWorkspaceChange(), so Git/change-map data of a same-named project could stay stale until the next refresh. Only one workspace is tested end to end.
- [note] The multi-workspace tray menu is covered by the Rust unit test only.
- [note] check_login skips "off by default" if the Run key already points at the debug exe; could misfire if an installed release writes the same name with another path.
- [note] Dot and menu lag by up to 5 s (recounted every 5 s; recorded).
- [note] watch.rs needs_you matches index.html toneOf/waitingNeedsYou; fixtures count 3 matches the rail.
