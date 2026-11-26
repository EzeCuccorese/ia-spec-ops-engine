# Surgical Changes

## Invariants
- **Minimal Diff**: Change only what is requested. Justify every edited file in one line or revert it before pushing.
- **No Drive-By Edits**: Do not refactor, rename, or move unrelated blocks; propose them in their own PR.
- **Format Only What You Edit**: Run formatters and autofixers only on files you changed.
- **Foreign Code Needs Approval**: Modifying another team's code, CI, deploy configs, dependencies, or shared contracts requires explicit approval; isolate shared changes in their own PR.
- **No Silent Scope Growth**: If scope must expand or touch unrelated modules, stop and explain why first.
- **Fixes in the Owning Branch**: Put review fixes and refactors in the PR branch that introduced the code, not a new stacked PR.
- **Small, Paired PRs**: Split oversized changes before review. For cross-service enabling PRs, open both together, link both ways, and document merge order.
- **Closed Delegation**: Give subagents a closed list of editable files and review their full diff before committing.
- **Evidence First**: Treat subagent claims as hypotheses until verified in code. Read real logs before blaming a component; verify workarounds by reading saved state back.
- **Merge & Test Hygiene**: After merging base, diff shared/config files against base. Keep unlaunched prod-config PRs in draft, pull shared branches before pushing, and prune duplicate tests.
