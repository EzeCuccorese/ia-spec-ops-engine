# Deploy Approvals

Covers every deploy gate: a CircleCI deploy hold, a GitHub environment, an Argo sync.

## Invariants
- **Staging**: contextual authorization is enough, scoped to one task and named repositories ("approve the deploys needed to test these repos"). Naming each job is not required; a standing blank check is never allowed.
- **Production, canary included**: the agent never approves or triggers it, and only hands over the link to approve.
- **`deploy_approvals.production`**: `never` (default) keeps that rule; `explicit` allows approving when the user names the exact job and target environment, where a bare "ok" is not enough. See `ai-governance config show`.
- **Doubt means production**: an environment not confirmed as non-production counts as production.
- **One at a time**: one authorization, one approval, now. Never reused, never inferred from "run the pipeline".
- **Trail and window**: record with `taskflow approve`; production respects `production-risk-window`.
