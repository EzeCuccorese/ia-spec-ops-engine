# Legacy to v2 disposition

| Legacy capability | v2 disposition | Reason |
| --- | --- | --- |
| `sdd init` plus global rule deployment | Replaced by repository-local `spec init` | No global mutation |
| Specify, plan, tasks | Rebuilt as explicit artifact transitions | Small recoverable state machine |
| Legacy verify harness | Replaced by explicit argv checks and immutable evidence | No skipped-as-pass behavior |
| `sdd finish` Git staging/push/cleanup | Rejected | Governance must not seize Git scope or history |
| Multi-agent adapter generation | Rejected for stable v2 | Only the used Codex contract is supported |
| Codex adapter | Rebuilt as owned root `AGENTS.md` | Real discovery plus reversible removal |
| Self-healing and autonomous audit claims | Not shipped | No reproducible evidence of benefit |
| MCP server | Not migrated | No current personal workflow requires it |
| Engineering rules catalog | Reference only | Rules return only when a real spec needs them |
| Workspace/Kubernetes/build tools | Frozen in `spec-devops/` | Outside AI governance and SDD |
| Global installer/uninstaller | Scheduled for removal at cutover | Unsafe ownership boundary |

The migration criterion is observed personal usefulness and safety, not feature-count parity.
