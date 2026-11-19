# ia-spec-ops-engine

A development framework for AI coding agents (Claude Code, OpenAI Codex and Google
Antigravity), built on two ideas: whatever can be deterministic runs as code, and whatever
reaches the model is as small as possible.

This repository is a [uv](https://docs.astral.sh/uv/) workspace with two independently
installable Python packages (Python 3.11+):

| Package | CLI | Purpose |
| --- | --- | --- |
| [`packages/ai-governance`](packages/ai-governance) | `ai-governance` | Per-agent installer (user/project scopes), engineering rules, corporate packs, third-party skills, agent hooks, task notebook & multi-provider design debates, Atlassian utilities |
| [`packages/workspace`](packages/workspace) | `ws` | Deterministic execution: stack detection, quality gates, Git hooks, design limits, and condensed command output |

`ai-governance` and `workspace` never import each other; `ai-governance` calls `ws` through
versioned `--json` contracts and degrades gracefully when it is absent.

Personal third-party skills live, versioned in git, in [`skills/`](skills). Company-specific
rule packs (rules, scripts and corporate skills) live, gitignored and never committed to git, in
[`packages/corporate-rules/<company>/`](packages/corporate-rules) and are installed by
`ai-governance`. Each package README is the reference for its CLI.

## Install

```bash
uv tool install ./packages/ai-governance   # add --editable to use corporate packs and personal skills from this checkout
uv tool install ./packages/workspace
```

Then follow [docs/getting-started.md](docs/getting-started.md) to set up one agent and one
repository and verify each piece.

## Development

```bash
uv sync --all-packages
uv run ruff check packages/ tests/ evals/ .github/scripts/
uv run ruff format --check packages/ tests/ evals/ .github/scripts/
uv run mypy
uv run python -m pytest -q --cov
```

## Gemini PR review: recommended trigger for consumers

Repositories that call `reusable-gemini-review.yml` run a full review on PR open, reopen,
`ready_for_review`, or on-demand via the `gemini-review` label (even on drafts). Including
`synchronize` runs an **incremental diff** review covering only commits pushed since the last
reviewed SHA (matching `.github/workflows/gemini-pr-review.yml`). Omit `synchronize` (and set
`cancel-in-progress: false`) if you prefer strictly one-shot reviews re-triggered only by adding
the `gemini-review` label.

```yaml
on:
  pull_request:
    types: [opened, reopened, ready_for_review, synchronize, labeled]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  # Cancel stale incremental runs on new pushes; keep labeled/open runs intact.
  cancel-in-progress: ${{ github.event.action == 'synchronize' }}

jobs:
  review:
    # Automatic on PR open/reopen/ready/synchronize (never for drafts); on demand with the
    # `gemini-review` label, even on drafts.
    if: >-
      (github.event.action == 'labeled' && github.event.label.name == 'gemini-review') ||
      (github.event.action != 'labeled' && github.event.pull_request.draft == false)
    uses: EzeCuccorese/ia-spec-ops-engine/.github/workflows/reusable-gemini-review.yml@v3.0.0
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

- Pin the reusable workflow to a release tag (e.g. `@v3.0.0`) or a full commit SHA rather than
  `@main`; `engine-ref` defaults to `v3.0.0` and should match the pinned release.
- Create the `gemini-review` label in each consumer repository.
- The caller needs `permissions: pull-requests: write` (and `contents: read`) so the review
  can post comments and `clear-label` can remove the label.
- To request a fresh full review at any time, add the `gemini-review` label to the PR; it is
  removed automatically once the run finishes.

## License

[MIT](LICENSE)
