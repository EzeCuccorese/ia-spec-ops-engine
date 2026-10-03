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

## Gemini PR review: recommended trigger for consumers

Repositories that call `reusable-gemini-review.yml` should run the review once per PR and
re-run it on demand with a label. Do not trigger on `synchronize`: it re-runs the review on
every push, so each fix produces a new batch of comments and the review never converges.

```yaml
on:
  pull_request:
    types: [opened, reopened, ready_for_review, labeled]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: false # an unrelated label event must not abort a review in progress

jobs:
  review:
    # Automatic once per PR (opened/reopened/ready, never for drafts); on demand with the
    # `gemini-review` label, even on drafts.
    if: >-
      (github.event.action == 'labeled' && github.event.label.name == 'gemini-review') ||
      (github.event.action != 'labeled' && github.event.pull_request.draft == false)
    uses: EzeCuccorese/ia-spec-ops-engine/.github/workflows/reusable-gemini-review.yml@main
    secrets: inherit

  clear-label:
    needs: review
    if: always() && github.event.action == 'labeled' && github.event.label.name == 'gemini-review'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - name: Remove the trigger label so it can be added again
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
        # The label may already be gone (removed by hand while the review ran).
        run: gh pr edit "${{ github.event.pull_request.number }}" --remove-label gemini-review || true
```

Notes:

- Create the `gemini-review` label in each consumer repository.
- The caller needs `permissions: pull-requests: write` (and `contents: read`) so the review
  can post comments and `clear-label` can remove the label.
- To request another review, add the `gemini-review` label to the PR; it is removed
  automatically once the run finishes.

## License

[MIT](LICENSE)
