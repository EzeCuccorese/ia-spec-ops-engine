# Atlassian (Jira & Confluence)

## Invariants
- **CLI**: use `ai-governance jira` and `ai-governance confluence`, not MCP or a browser. The instance URL comes from `$ATLASSIAN_URL`.
- **Reads are free**: `jira issue|search|comments`, `confluence read|search|spaces`.
- **Writes need approval**: show a preview of the exact content and target, then wait for the user's approval before create, update, comment, transition or assign.
- **Confluence read gotcha**: `confluence read` flattens tables and drops macros and child-page links. For rich pages read `body.storage` from the REST API.
- **Confluence write gotcha**: `confluence update` can corrupt existing macros and tables. To edit a rich page, PUT `body.storage` with `version.number` + 1, keeping the original HTML and adding only the delta.
- **Jira formatting**: `jira create|update` already converts headings and checkboxes; never hand-build ADF. If a ticket renders wrong, tell the user before working around the tool.
