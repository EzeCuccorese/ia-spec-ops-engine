# CircleCI Operations

## Invariants
- **Read Operations**: CircleCI reads (pipeline, workflow, job status, logs, artifacts) are free and require no prior authorization.
- **Mutations Require Approval**: Any POST or DELETE operation (rerun, cancel, approve, environment variable changes) requires the user's explicit approval after showing the exact action and target.
- **No Deploy Approvals**: Never approve a deploy hold.
- **Token Safety**: Tokens must only be named by variable (`CIRCLE_TOKEN`, `CIRCLE_TOKEN_RW`), never by value.
