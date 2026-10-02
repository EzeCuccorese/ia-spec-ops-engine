# ia-spec-ops-engine

A development framework for AI coding agents (Claude Code, OpenAI Codex and Google
Antigravity), built on two ideas: whatever can be deterministic runs as code, and whatever
reaches the model is as small as possible.

This repository is a [uv](https://docs.astral.sh/uv/) workspace with three independently
installable Python packages (Python 3.11+):

| Package | CLI | Purpose |
| --- | --- | --- |
| [`packages/ai-governance`](packages/ai-governance) | `ai-governance` | Per-agent installer (user/project scopes), engineering rules, corporate packs, agent hooks, progress tracking, Claude spend telemetry, Atlassian utilities |
| [`packages/workspace`](packages/workspace) | `ws` | Deterministic execution: stack detection, quality gates, Git hooks, condensed command output, worktrees, local services |
| [`packages/spec`](packages/spec) | `spec` | Specification-driven workflows (archived for now) |

`ai-governance` and `workspace` never import each other; `ai-governance` calls `ws` through
versioned `--json` contracts and degrades gracefully when it is absent.

Company-specific rule packs live, gitignored, in
[`packages/corporate-rules/<company>/`](packages/corporate-rules) and are installed by
`ai-governance`. Each package README is the reference for its CLI.

## Install

```bash
uv tool install ./packages/ai-governance   # add --editable to use corporate packs from this checkout
uv tool install ./packages/workspace
```

Then follow [docs/getting-started.md](docs/getting-started.md) to set up one agent and one
repository and verify each piece.

## Development

```bash
uv sync --all-packages
uv run ruff check packages/ tests/ evals/
uv run ruff format --check packages/ tests/
uv run mypy
uv run python -m pytest -q --cov
```

## License

[MIT](LICENSE)
