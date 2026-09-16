# ia-spec-ops-engine

A source repository for three independently installable Python packages. It does not bootstrap, install, or configure anything by default.

| Package | Purpose | Installed only when explicitly requested |
| --- | --- | --- |
| `packages/ai-governance` | Rules, progress tracking, telemetry, context frugality, and Atlassian utilities | Yes |
| `packages/workspace` | Git worktrees, quality gates, local services, and environment tools | Yes |
| `packages/spec` | Specification workflows and coding-agent adapters | Yes |

Tell the coding agent which package and capability you want. For example: “Use `ai-governance` rules for Python and core practices in this repository” or “Install only the Workspace Git-hook tooling.” The agent must inspect the requested component and propose the exact installation before making changes.

`ai-governance` already groups its rules into core practices, language stacks, infrastructure, and documentation. Its other capabilities—progress, telemetry, frugality, Jira, and Confluence—need an explicit component model before they can be installed or uninstalled independently.
