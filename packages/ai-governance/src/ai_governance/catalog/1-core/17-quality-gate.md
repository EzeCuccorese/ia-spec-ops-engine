# Quality Gate & Delegation

## Invariants
- **Never bypass hooks**: never use `--no-verify`. If a gate check fails for a reason unrelated to the change, explain it and offer to skip only that check (`QG_SKIP=<check> git push`).
- **Own tests are never skipped**: tests covering the current change always run.
- **No duplicate runs**: do not run tests, lint or type checks by hand when the pre-push gate already runs them, unless iterating on a failure.
- **Fewer turns**: batch independent shell commands in one call; use a script to build and filter in one step.
- **Delegation**: delegate to a subagent only when the input is small, the work is large and the needed output is small. Every delegation prompt sets an output budget (e.g. "return at most N lines, absolute paths, no code dumps").
