# Pull Request Descriptions

## Invariants
- **One Outcome per PR**: Deliver one user outcome per PR; split two into two PRs. Branch from main; never stack PRs without approval.
- **Plain Language**: Use the repo's language and short sentences; never mention internal tooling. Bot summaries never replace this description.
- **Review Readiness**: After pushing, follow checks and bot reviews for the latest commit and fix failures instead of offering to check later. Never request review with open bot threads or conflicts.
- **Production Accountability**: Merged is not Done—Done means deployed and validated in prod. State outcome metric, counter-metric, and intentional debt.

## Required Structure (in order)
1. **Outcome**: 2–3 lines on what the user or customer gains.
2. **Flow**: Mermaid diagram (≤8 nodes) showing the change.
3. **What it adds**: One line per added capability or component.
4. **What does not change**: Explicit untouched boundaries.
5. **External impact**: What it touches outside the team's code and why, or "nothing".
6. **Safety**: Error handling, permissions, and prod impact.
7. **Size**: Code lines versus test lines changed.
8. **Evidence**: Test and end-to-end evidence, shown to the user before uploading.
9. **Dependencies**: Upstream/downstream dependencies and merge order.
10. **Open items**: One named person per item (never "the team"), or "no owner" with a question.
