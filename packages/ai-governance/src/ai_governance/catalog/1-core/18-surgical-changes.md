# Surgical Changes

## Invariants
- **Minimal Diff**: Change only what the request requires. Be ready to justify every modified file in one line, or revert it before pushing.
- **No Drive-By Edits**: Do not refactor, rename, or move unrelated blocks in existing code; propose them separately in their own PR.
- **Format Only What You Edit**: Run formatters and autofixers only on the files you changed.
- **Foreign Code Needs Approval**: Modifying another team's code, CI, deploy configs, dependencies, or shared contracts requires explicit user approval; put shared changes in their own PR.
- **No Silent Scope Growth**: When a change requires expanding beyond the agreed scope or touching unrelated modules, stop and explain why to the user first.
- **Fixes in the Owning Branch**: Review fixes, refactors and technical decisions go in the branch of the PR that introduced the code, not in a new stacked PR. Open a new branch only for a feature reviewable on its own.
- **Small, Paired PRs**: Split oversized changes before review. When a change requires an enabling PR in another service, open both PRs together, link them both ways, and document the merge order.
- **Closed Delegation**: Give subagents a closed list of editable files, and review their full diff before committing.
- **Evidence First**: Treat subagent claims as hypotheses until verified in code. Read real logs before blaming a component, and verify workarounds by reading the saved state back.
