# Taskflow & Task Registry

## Invariants
- **Task Tracking**: Register and track multi-step or multi-session work with the task registry via `ai-governance taskflow` commands (`here`, `status`, `new`, `bind`).
- **Record Progress**: Record progress incrementally with `step add|done`, `fact`, and `decide --why`.
- **Gates & Approvals**: Advance through workflow phases with `phase <id> <phase>`; record user authorizations for sensitive actions using `approve <id> --action <a> --target <t> --user-reply "<reply>"`.
