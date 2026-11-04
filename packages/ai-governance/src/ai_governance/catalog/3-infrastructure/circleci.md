# CircleCI Operations

## Invariants
- **Reads are free**: pipeline, workflow and job status, logs and artifacts, using `CIRCLE_TOKEN` (read-only).
- **Writes need approval**: any POST or DELETE (rerun, cancel, approve a hold, trigger a pipeline, change env vars or contexts) requires showing the exact action and target, then the user's explicit approval. Use `CIRCLE_TOKEN_RW` only for an approved action.
- **No deploy approvals**: never approve a deploy hold.
- **Token safety**: name tokens only by variable, never by value.
