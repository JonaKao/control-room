# Definition of done: api-client

A task is finished only when every item below holds. The reviewer checks each one.

## Always

- [ ] Every check in `project.json` passes (`python3 framework/aaf.py check api-client`)
- [ ] No check, test or threshold was weakened, skipped or removed to get there
- [ ] The task's own success is covered by a check, not only by manual inspection
- [ ] The reviewer subagent returned PASS
- [ ] `state/progress.md` says what changed and what is next

## Project-specific

- [ ] Every public function has a docstring and a type hint
