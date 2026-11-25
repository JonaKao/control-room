# Review: F7 Icon and installer

VERDICT: PASS
SUMMARY: F7 meets the spec; 17/17 checks pass incl. the new Installer check; the desktop-icon part of that check cannot tell whether the hook is there.

## Findings
- [minor] checks/installer.py: the desktop-icon test looks for `CreateShortcut "$DESKTOP` in the generated script plus hooks.nsh, but Tauri's template always contains that line (CreateOrUpdateDesktopShortcut, run only if the finish-page box is ticked or in silent/passive installs). Without installerHooks in tauri.conf.json the check would still pass. Require installerHooks, the $DESKTOP CreateShortcut inside NSIS_HOOK_POSTINSTALL in the hook file, and the script's !include of it.
- [note] desktop.py "in front" now checks the stacking order (decision recorded); GetTopWindow/GetWindow keep ctypes' c_int return type (a handle with the high bit set would not compare equal; unlikely).
- [note] installer.py reads build output outside Git; fails on a fresh clone until build.py ran (spec allows).
- [note] hooks.nsh re-creates a deleted desktop icon on upgrade (acceptable).
- [note] render-installed-start-menu.png (0.1.0) still shows the fixed horizontal scrollbar; the desktop-icon capture (0.1.1) does not.
- [note] Installed: 0.1.1; built: 0.1.2 (with the window-to-front change), not installed.
