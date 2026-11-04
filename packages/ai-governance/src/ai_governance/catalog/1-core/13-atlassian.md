# Atlassian (Jira & Confluence)

## Invariants
- **CLI Commands**: Use `ai-governance jira` and `ai-governance confluence` to interact with Jira and Confluence. The instance URL comes from `$ATLASSIAN_URL`.
- **Read Operations**: Reads are free and require no prior authorization (`jira issue`, `jira search`, `jira comments`, `confluence read`, `confluence search`, `confluence spaces`).
- **Writes Require Approval**: Any mutating operation (create, edit, comment, transition, assign, delete, update, append) requires the user's explicit approval after showing the exact action and target.
