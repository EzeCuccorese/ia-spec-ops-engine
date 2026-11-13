# Pull Request Descriptions

## Invariants
- **One Outcome per PR**: One thing the user or customer gains; two outcomes are two PRs. Branch from the main branch; no stacked PRs without approval.
- **Fixed Order**: 1) outcome in 2-3 lines, in customer terms; 2) Mermaid flow, at most 8 nodes; 3) what it adds, one line each; 4) what does not change; 5) what it touches outside the team's code and why, or "nothing"; 6) how it stays safe (errors, permissions, production impact); 7) size, code vs tests; 8) tests and end-to-end evidence, shown to the user before upload; 9) dependencies and merge order; 10) one owner per open item.
- **Named Owners**: Each open item has one person, or "no owner" plus a question to the user.
- **Plain Language**: Repo language, short sentences, no internal tooling; a bot summary replaces none of this.
- **Review Readiness**: No review request with open bot threads or merge conflicts.
