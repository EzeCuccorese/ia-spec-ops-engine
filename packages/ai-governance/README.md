# ai-governance

Per-agent engineering standards, token frugality, Claude spend telemetry and lightweight
task tracking for AI coding agents. Supported agents: **Claude Code**, **OpenAI Codex** and
**Google Antigravity 2**. The installer is a deterministic CLI: you choose the agent(s),
and only those agents' files are touched.

Deterministic execution (stack detection, quality gates, condensed command output, Git
hooks) lives in the sibling `workspace` package (`ws`); `ai-governance` calls it through
versioned `--json` contracts and degrades gracefully when it is missing.

## Install

Step-by-step walkthrough with verification: [docs/getting-started.md](../../docs/getting-started.md).

```bash
uv tool install ./packages/ai-governance   # CLI: ai-governance
uv tool install ./packages/workspace       # CLI: ws (recommended)
```

## What gets installed where

### User scope — `ai-governance install --scope user --agent <claude|codex|antigravity>`

Personal, project-agnostic harness. Nothing about engineering policy.

<!-- agents-table:start -->
| | Claude Code | OpenAI Codex | Google Antigravity 2 |
|---|---|---|---|
| Global instructions | ~/.claude/rules/ai-governance.md | $CODEX_HOME/AGENTS.md (marker block) | ~/.gemini/config/rules/ai-governance.md (`trigger: always_on`) |
| Global hooks | ~/.claude/settings.json (Pre/PostToolUse Bash, Stop, SessionStart/End) | $CODEX_HOME/hooks.json PostToolUse condensing (after `probe` verifies) | antigravity-cli/hooks.json PreToolUse: raw noisy commands -> `ws run` (after `probe`) |
| Scout subagent | ~/.claude/agents/scout.md (sonnet, effort medium) | $CODEX_HOME/agents/scout.toml (terra, effort medium, read-only) + config.toml default subagent model terra | ~/.gemini/config/agents/scout.md (model flash, read-only tools, no commands) |
| Progress skill | ~/.claude/skills/progress/SKILL.md | ~/.agents/skills/progress/SKILL.md | ~/.gemini/config/skills/progress/SKILL.md |
| Project rules | .claude/rules/ai-governance-<id>.md -> symlink to .agents/rules | .agents/rules/ai-governance-<id>.md (shared) | .agents/rules/ai-governance-<id>.md (single source) |
| Rule loading | native `paths:` frontmatter (loaded per file) | injected on edit by a PreToolUse hook (planned) | `trigger: glob` activation (loaded per file; 20k-token rules budget) |
<!-- agents-table:end -->

The read-only `scout` subagent is cross-agent: each agent gets it with a cheap model of its
own provider (Claude `sonnet`, Codex `terra` — also set as Codex's default subagent model in a
marked block of `config.toml` — and Antigravity `flash`). `ai-governance probe` verifies that
each agent really delegates to it. The Claude scout sets `omitClaudeMd: true` (it runs without
CLAUDE.md/AGENTS.md instructions, saving tokens); the Antigravity scout is limited to
`view_file`, `grep_search`, `find_by_name`, `list_dir` with `commandExecutionPolicy: off`. A
misspelled tool name can hang an Antigravity subagent, so run
`ai-governance probe --agent antigravity` to verify it after installing.

Claude Code user hooks (all through `ai-governance hook claude <event>`, fail-open):

| Event | Effect |
|---|---|
| PreToolUse (Bash) | One-line advice when a deterministic tool replaces the command |
| PostToolUse (Bash) | Replaces large output with the `ws condense` summary (`ws log <id>` keeps the full text) |
| SessionStart | Injects the active task digest (≤ 400 chars) |
| SessionEnd | Logs branch, HEAD and uncommitted files to the active task |
| Stop | Spend threshold alerts (macOS notification; never reaches the model) |

State: `~/.local/state/ai-governance/` (ledger `installed.json`, progress, telemetry).
Config: `~/.config/ai-governance/` (`frugal.json`, `atlassian.json`).

### Project scope — `ai-governance install --scope project --agent <...>`

Team policy, committed to the repository:

- Rules for the stacks detected by `ws detect` (e.g. Java rules only in Java repos),
  rendered into each chosen agent's own folder and loaded per file.
- One shared `AGENTS.md` block (the only instructions file; any `CLAUDE.md` is migrated
  into `AGENTS.md`, because Claude Code ignores `AGENTS.md` while a `CLAUDE.md` exists).
- Claude Code `Stop` gate: `ws check --changed --cache`, blocking the turn end once with a
  condensed failure summary (`gate = false` in the config disables it).
- `.ai-governance/config.toml` (agents, profiles, extra/excluded rules, gate) and
  `.ai-governance/lock.json` (ownership ledger). Commit both and the generated files.

### Profiles

Most rules apply automatically once their stack or path is detected. Three groups are opt-in,
enabled per project with `--profile`:

| Profile | Covers | Rules |
|---|---|---|
| `architecture` | Clean/hexagonal architecture, DDD, refactoring and strangler fig | `02-clean-architecture-hexagonal`, `03-ddd-domain-modeling`, `10-refactoring-strangler` |
| `distributed` | Event-driven architecture, resilience and concurrency | `07-event-driven-architecture`, `08-resilience-fault-tolerance`, `09-concurrency-locking` |
| `api` | API design and observability | `api-design`, `observability` |

```bash
ai-governance rules profiles                                       # list profiles and their rules
ai-governance install --scope project --profile architecture       # enable a profile
ai-governance uninstall --scope project --profile architecture     # disable it, agents untouched
```

The `architecture` profile also enables the `ws design` layer-boundary check (see
`packages/workspace/README.md`), configured via `[design.layers]` in `.ai-governance/config.toml`.

`ai-governance update` removes the rules of a profile that is no longer enabled and reports a
hint to re-enable it.

## Everyday commands

| Command | Purpose |
|---|---|
| `ai-governance update [--all] [--check] [--dry-run]` | Re-detect stacks and refresh only the applicable rules; local edits are kept and reported; `--check` fails CI on drift |
| `ai-governance uninstall --scope ... --agent ...` | Remove exactly what was written |
| `ai-governance status` / `doctor` | What is installed where / read-only health checks |
| `ai-governance budget` | Fixed context bytes (~tokens) each agent loads every session |
| `ai-governance probe --agent <a>` then `--verify --seen ...` | Proves on this machine which instruction locations the agent loads and which hooks fire. Codex/Antigravity hooks are installed only after a verified probe |
| `ai-governance rules list` / `rules show <id>` / `rules profiles` | Browse the rule catalog and opt-in profiles |
| `ai-governance progress here\|new\|show\|step\|fact\|close` | Compact cross-session task state |
| `ai-governance telemetry claude-usage` | Month-to-date Claude spend vs. business-day budget (for plans whose UI hides spend) |
| `ai-governance telemetry report\|thresholds\|calibrate\|prices update` | Estimates, alerts, calibration, price cache |
| `ai-governance jira ...` / `confluence ...` | Atlassian as compact Markdown |

Installs are idempotent and reversible: an ownership ledger records every file, block and
hook entry; files you edited are never overwritten, foreign files are never replaced
without `--force`, and `--dry-run` shows the exact plan.

## Agent output mode

CLIs print compact plain text when run by an agent, detected from `CLAUDE_CODE_CHILD_SESSION`,
`CLAUDECODE`, `CODEX_SANDBOX` or `ANTIGRAVITY_AGENT`. Override with `AI_GOVERNANCE_AGENT=1|0`.
A plain pipe keeps full human output.

## Environment

| Variable | Effect |
|---|---|
| `AI_GOVERNANCE_STATE_DIR` / `AI_GOVERNANCE_CONFIG_DIR` | Override state / config locations (XDG defaults) |
| `AI_GOVERNANCE_AGENT` | Force agent (`1`) or human (`0`) output |
| `CODEX_HOME` | Codex home (default `~/.codex`) |
| `FRUGAL=0` or `#nofrugal` in a command | Disable condensing for that command |
| `ATLASSIAN_PROFILE`, `ATLASSIAN_{URL,EMAIL,API_TOKEN}` | Jira/Confluence credentials |
