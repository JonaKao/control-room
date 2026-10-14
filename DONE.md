# Definition of done: control-room

A task is finished only when every item below holds. The reviewer checks each one.

## Always

- [ ] Every check in `project.json` passes (`python3 framework/aaf.py check control-room`)
- [ ] No check, test or threshold was weakened, skipped or removed to get there
- [ ] The task's own success is covered by a check, not only by manual inspection
- [ ] The reviewer subagent returned PASS
- [ ] `state/progress.md` says what changed and what is next
- [ ] The screenshots in `plots/render-*.png` were opened and inspected after the change

## Project-specific

- [ ] Every fixture project renders without JavaScript errors in light, dark and phone views
- [ ] No sideways scrolling at phone width (390 px)
- [ ] Someone who does not know the code can tell, from the top of the page alone,
      what the agent is doing right now and whether anything needs them
- [ ] The page is calm: grouped into clear sections, important things first, detail
      available on demand rather than all shown at once
- [ ] Information is shown visually wherever a picture says it better than text
- [ ] Wording is plain language; internal terms (phase names, file names) are explained or avoided
- [ ] The server writes no project files itself (Git only through `aaf.py`, page-only requests) and still rejects path traversal (API tests)

## When stuck, report

- What you tried, in order, and why each attempt failed
- The failing check output (shortened) and the relevant screenshot
- The one decision or piece of information you need from the human
