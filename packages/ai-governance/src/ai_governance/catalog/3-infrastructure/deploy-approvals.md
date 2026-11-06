# Deploy Approvals

## Invariants
- **Explicit Authorization Only**: Deploy approvals (CircleCI deploy holds, GitHub environments, Argo CD sync/promote) require explicit user authorization; a bare "ok" is never sufficient.
- **Named Job and Environment**: Prompt and approval must name the exact job/workflow and target environment. Staging approval never covers production; jobs without explicit environment are prohibited.
- **Point-in-Time Grant**: Authorization is an immediate single-turn grant for that action. Never reuse prior authorizations or infer approval from indirect requests (e.g. "run the pipeline").
- **Single-Action Scope**: One authorization covers one approval; never extends to another job, environment, or rerun.
- **Audit Trail**: Record each approval with `taskflow approve`.
- **Production Risk Window**: Production approvals must respect `production-risk-window`; outside the safe window, defer execution to the next business day.
