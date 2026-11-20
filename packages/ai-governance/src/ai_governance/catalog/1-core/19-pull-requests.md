# Pull Request Descriptions

## Invariants
- **One Outcome per PR**: Deliver one user or customer outcome per PR; split two outcomes into two PRs. Branch from the main branch, and never stack PRs without user approval.
- **Plain Language**: Write in the repository's language using short sentences, and never mention internal tooling. An automated bot summary never replaces this description.
- **Review Readiness**: After pushing, follow checks and automated review for the latest commit and fix what fails instead of offering to check later; re-read bot comments that arrive after each push. Never request a review while automated bot review threads remain open or merge conflicts exist.

## Required Structure (in order)
1. **Outcome**: 2–3 lines explaining what the user or customer gains.
2. **Flow**: A Mermaid diagram of at most 8 nodes showing the change.
3. **What it adds**: One line per added capability or component.
4. **What does not change**: Explicit boundaries left untouched.
5. **External impact**: What it touches outside the team's code and why, or "nothing".
6. **Safety**: Error handling, permissions, and production impact.
7. **Size**: Code lines versus test lines changed.
8. **Evidence**: Test results and end-to-end evidence, shown to the user before uploading.
9. **Dependencies**: Upstream/downstream dependencies and merge order.
10. **Open items**: Each open item needs one named owner, or "no owner" paired with a question to the user.
