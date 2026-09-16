# ia-spec-ops-engine

A source repository for three independently installable Python packages. It does not bootstrap, install, or configure anything by default.

| Package | Purpose | Installed only when explicitly requested |
| --- | --- | --- |
| `packages/ai-governance` | Rules, progress tracking, telemetry, context frugality, and Atlassian utilities | Yes |
| `packages/workspace` | Git worktrees, quality gates, local services, and environment tools | Yes |
| `packages/spec` | Specification workflows and coding-agent adapters | Yes |

Tell the coding agent which package and capability you want. For example: “Use `ai-governance` rules for Python and core practices in this repository” or “Install only the Workspace Git-hook tooling.” The agent must inspect the requested component and propose the exact installation before making changes.

`ai-governance` already groups its rules into core practices, language stacks, infrastructure, and documentation. Its other capabilities—progress, telemetry, frugality, Jira, and Confluence—need an explicit component model before they can be installed or uninstalled independently.

## Development

This repo is a [uv](https://docs.astral.sh/uv/) workspace: all three packages share a single `.venv` at the repository root.

```bash
# Create the shared .venv with the three packages + dev tools
uv sync --all-packages

# Run the whole test suite
uv run pytest

# Lint and type-check
uv run ruff check
uv run mypy
```

To install a single package elsewhere (outside this workspace), use a standalone editable install:

```bash
uv pip install -e packages/<pkg>   # e.g. packages/spec, packages/workspace, packages/ai-governance
```
