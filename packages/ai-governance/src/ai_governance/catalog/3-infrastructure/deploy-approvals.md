# Deploy Approvals

Applies to every deploy gate: a CircleCI deploy hold, a GitHub deployment environment, or an Argo sync.

## Invariants
- **Staging**: Contextual authorization is enough when scoped to one task and named repositories (for example, "approve the deploys needed to test these repos"). Naming each job is not required, but a standing blank check is never allowed.
- **Production (including canary)**: Governed by `deploy_approvals.production` (inspect with `ai-governance config show`):
  - `never` (default): The agent never approves or triggers production deploys, and only hands over the approval link to the user.
  - `explicit`: Allows approving only when the user names the exact job and target environment in an explicit phrase (a bare "ok" is not enough), and only within `production-risk-window`.
- **Doubt Means Production**: Any environment not confirmed as non-production is treated as production.
- **One at a Time**: Each authorization covers one immediate approval only—never reuse it or infer it from "run the pipeline".
- **Audit Trail**: Record every deploy approval with `ai-governance taskflow approve`.
