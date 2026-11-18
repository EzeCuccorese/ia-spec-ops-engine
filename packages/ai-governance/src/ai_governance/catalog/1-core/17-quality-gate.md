# Quality Gate & Delegation

## Invariants
- **Never Bypass Hooks**: Never run `git push --no-verify`. If a gate check fails for a reason unrelated to your change, explain the failure to the user and offer to skip only that check (`QG_SKIP=<check> git push`).
- **Own Tests Always Run**: Never skip tests covering your current change. Run `ws check --changed` after code edits to verify changed files and targeted tests quickly.
- **No Duplicate Full Runs**: Once `ws check --changed` passes, do not re-run the full test, lint, or type-check suite manually when the pre-push gate is about to run it, unless you are iterating on a failure.
- **Fewer Turns**: Batch independent shell commands into one call, and filter noisy build or test output in one step (for example with `ws run`).
- **Bounded Delegation**: Delegate to a subagent only when the input is small, the work is large, and the needed output is small. Every delegation prompt must set an output budget (e.g., "return at most N lines with absolute paths and no code dumps").
