# Review: F9 Plain README for the app

VERDICT: PASS
SUMMARY: The README explains the desktop app plainly, follows the template order and matches the code; 18/18; the README test fails when any required name is removed (mutation-tested).

## Findings
- [note] README "Click the icon to open the window" is true on Windows only; on a Mac any click opens the menu.
- [note] test_readme swaps the browser-version names for the app's (not a weakening); some required words are common.
- [note] ROADMAP item 9 is Done while F10 is open (as the spec asks).
- [note] plots changed only because the check run redrew them.
