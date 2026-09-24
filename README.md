# ia-spec-ops-engine

A development framework for AI coding agents — **Claude Code, OpenAI Codex and Google
Antigravity 2** — built on two ideas: whatever can be deterministic runs as code (zero
tokens, same result every time), and whatever reaches the model is as small as possible.

The repository is a source checkout with three independently installable Python
packages. It does not bootstrap, install, or configure anything by default.

| Package | CLI | Purpose |
| --- | --- | --- |
| `packages/ai-governance` | `ai-governance` | Per-agent installer (user/project scopes), engineering rules, agent hooks, progress tracking, Claude spend telemetry, Atlassian utilities |
| `packages/workspace` | `ws` | Deterministic execution: stack detection, quality gates, Git hooks, condensed command output, worktrees, local services |
| `packages/spec` | `spec` | Specification-driven workflows (archived for now) |

`ai-governance` and `workspace` never import each other; `ai-governance` calls `ws` through
versioned `--json` contracts (`ws detect`, `ws condense`, `ws check`) and degrades
gracefully without it. The agent-detection env markers are shared by convention and
guarded by a contract test.

**New here? Follow [docs/getting-started.md](docs/getting-started.md)**: install, set up one agent
and one repository, and verify every piece step by step.

## Global vs. project

| | User scope (`--scope user`) | Project scope (`--scope project`, committed) |
|---|---|---|
| Purpose | Personal, project-agnostic harness | Team policy for one repository |
| Instructions | ≤1 KB block in each agent's global file | One shared `AGENTS.md` block (no `CLAUDE.md`) |
| Rules | none | Only the rules for the detected stacks, in each agent's own folder, loaded per file |
| Hooks | Output condensing, pre-shell advice, session progress, spend alerts | Quality gate when the agent ends a turn |
| Subagents / skills | Read-only `scout` (cheap model, medium effort), `progress` skill | — |
| Git | Optional global gate (`ws hooks install --global`, config-based hooks) | `ws hooks install` |

You always choose the agent(s) (`--agent claude|codex|antigravity`); nothing is installed
for agents you did not select. See `packages/ai-governance/README.md` for the exact files.

```bash
uv tool install ./packages/ai-governance && uv tool install ./packages/workspace
ai-governance install --scope user --agent claude
cd my-repo && ai-governance install --scope project --agent claude --agent codex
ai-governance update --all      # after upgrading: refresh only the rules each project needs
ai-governance budget            # fixed context each agent loads per session
```

## Development

This repo is a [uv](https://docs.astral.sh/uv/) workspace: all three packages share a
single `.venv` at the repository root.

```bash
uv sync --all-packages                 # shared .venv with the three packages + dev tools
uv run pytest                          # whole test suite
uv run ruff check && uv run ruff format --check packages/ tests/
uv run mypy
```

CI runs the same checks plus a wheel build and a hermetic smoke test of the installed
wheels (`tests/integration/verify_wheels.py`). The repo's own pre-push quality gate
(`.githooks/pre-push`) runs secrets scan, commit policy, lint and tests before every push.

To install a single package elsewhere (outside this workspace):

```bash
uv pip install -e packages/<pkg>   # packages/ai-governance, packages/workspace, packages/spec
```
