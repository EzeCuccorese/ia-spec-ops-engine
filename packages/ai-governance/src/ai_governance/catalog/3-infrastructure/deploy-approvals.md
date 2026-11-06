# Deploy Approvals

## Invariants
- **Staging and Non-Production Environments**: Contextual authorization is sufficient when scoped to a specific task and set of repositories (e.g. "authorized to approve all deploys required for testing these repos"). It does not require naming every individual job or pipeline, but must remain bounded to that task and repository scope rather than a permanent blank check.
- **Production Environments (Including Canary)**: The agent never approves or triggers a production deploy. The agent may only provide the target link for the user to review and approve directly.
- **Configurable Production Policy (`deploy_approvals.production`)**:
  - `never` (default): The agent never approves or triggers production deploys under any circumstances; it only passes the link to the user.
  - `explicit`: Production deploys are permitted only with explicit user authorization naming the exact job/workflow and target environment; a bare "ok" is never sufficient.
  Inspect the active configuration with `ai-governance config show`.
- **Ambiguity Treated as Production**: When in doubt between staging and production, or if an environment cannot be definitively confirmed as non-production, always treat it as production.
- **Audit Trail**: Record each approval with `taskflow approve`.
- **Production Risk Window**: Any production deploy actions must respect `production-risk-window`; outside the safe window, defer execution to the next business day.
- **Deploy Holds and Actions**: Applies to all deployment gates and promotions, including CircleCI deploy holds, GitHub environments, and Argo CD sync/promote actions.
