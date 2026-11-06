# Tool Confidentiality

## Invariants
- **Confidential Engine Tooling**: Engine tooling (`ai-governance`, `ws`, `taskflow`, quality gate, `QG_SKIP`, internal hooks, scripts, or orchestrators) is never mentioned in tickets, PRs, commits, reviews, Confluence or chat tools. Quality gate and `QG_SKIP` count as engine tooling.
- **Clean Artifacts**: Keep all external descriptions, commit messages, and review comments focused strictly on domain and code changes without referencing internal tooling.
