# Surgical Changes

## Invariants
- **Minimal Diff**: Change only what the request needs; justify each file in one line or revert it before pushing.
- **No Drive-By Edits**: No refactors, renames or moved blocks in existing code; propose apart.
- **Format Only What You Edit**: Formatters and autofix run on edited files only.
- **Foreign Code Needs Approval**: Other teams' code, CI, deploy config, dependencies and shared contracts need the user's approval; shared changes go in their own PR.
- **No Silent Scope Growth**: Needing another file means stop and explain why first.
- **Small, Paired PRs**: Split before review; a change another service must enable is paired from the start, linked both ways with merge order.
- **Closed Delegation**: Subagents get a closed list of editable files; review their full diff before commit.
- **Evidence First**: Subagent claims are hypotheses until checked in code; read real logs before blaming a component; verify workarounds by reading data back.
