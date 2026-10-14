VERDICT: PASS
SUMMARY: The live activity feed does what the task asks. All 5 checks pass, the new activity check catches real breakage (QUIET_MIN, waitingNeedsYou and reviewer badge mutations all fail it), and the screenshots match.

FINDINGS
- [minor] tests/test_api.py: ActivityTailTest sits after the `if __name__ == "__main__"` block; `python3 tests/test_api.py` would skip it (unittest discover still runs it).
- [minor] index.html quietFor/waitingNeedsYou: the hook has no PostToolUse event, so after the human grants a permission the newest entry stays "waiting for your permission" until the next tool call; a long approved command keeps showing "Needs you in Claude Code". Comes from framework/hooks/activity.py (out of scope); follow-up.
- [minor] index.html: in the quiet state the summary flag still says "Nothing needs you. It will keep going on its own" beside "no new step for 20 min".
- [minor] index.html: for a stuck or draft-waiting project whose newest entry is "waiting", the "Needs you in Claude Code" flag replaces the more specific stuck/decide message, and the rail dot turns from red to blue.
- [minor] index.html: the detail re-renders every 30 s even with unchanged data; open sections are kept, but text selection (and possibly the Git slot) may be disturbed.

DONE.md: every item met (5/5 checks pass; nothing weakened; covered by checks/activity.py and API tests; progress.md updated; screenshots inspected; fixtures render in light/dark/phone; no sideways scroll; summary answers what/needs-you; calm with detail on demand; visual icons; plain language; server only reads, traversal tests pass).
