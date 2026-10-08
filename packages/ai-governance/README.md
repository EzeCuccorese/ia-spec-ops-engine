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

Corporate packs are read from the source checkout, so install with
`uv tool install --editable ./packages/ai-governance` when you use them (or point
`AI_GOVERNANCE_CORPORATE_DIR` at the packs folder).

## What gets installed where

`install` and `uninstall` take `--scope user|project` (default `project`), one or more
`--agent claude|codex|antigravity` (repeatable), `--root` (project root, default the current
directory), `--dry-run` and, for `install`, `--force`. Without `--agent`, an interactive
terminal asks which agents to use; an agent or a non-interactive shell gets an error instead.
Nothing ever defaults to all agents.

### User scope — `ai-governance install --scope user --agent <claude|codex|antigravity>`

Personal, project-agnostic harness. Nothing about engineering policy.

<!-- agents-table:start -->
| | Claude Code | OpenAI Codex | Google Antigravity 2 |
|---|---|---|---|
| Global instructions | ~/.claude/rules/ai-governance.md | $CODEX_HOME/AGENTS.md (marker block) | ~/.gemini/config/rules/ai-governance.md (`trigger: always_on`) |
| Global hooks | ~/.claude/settings.json (Pre/PostToolUse Bash, Stop, SessionStart/End) | $CODEX_HOME/hooks.json PostToolUse condensing (after `probe` verifies) | ~/.gemini/config/hooks.json PreToolUse: raw noisy commands -> `ws run` (after `probe`) |
| Scout subagent | ~/.claude/agents/scout.md (sonnet, effort medium) | $CODEX_HOME/agents/scout.toml (terra, effort medium, read-only) + config.toml default subagent model terra | ~/.gemini/config/agents/scout.md (model flash, read-only tools, no commands) |
| Skills | ~/.claude/skills/{progress,test-audit}/SKILL.md | ~/.agents/skills/{progress,test-audit}/SKILL.md | ~/.gemini/config/skills/{progress,test-audit}/SKILL.md |
| Project rules | .claude/rules/ai-governance-<id>.md -> symlink to .agents/rules | .agents/rules/ai-governance-<id>.md (shared) | .agents/rules/ai-governance-<id>.md (single source) |
| Rule loading | native `paths:` frontmatter (loaded per file) | injected on edit by a PreToolUse hook (planned) | `trigger: glob` activation (loaded per file; 20k-token rules budget) |
<!-- agents-table:end -->

The read-only `scout` subagent is cross-agent: each agent gets it with a cheap model of its
own provider (Claude `sonnet`, Codex `terra`, Antigravity `flash`). For Codex, a marked block
at the top of `$CODEX_HOME/config.toml` also sets `agents.default_subagent_model = "terra"`
and `agents.default_subagent_reasoning_effort = "medium"`; if the file already defines an
`[agents]` table or those keys, the block is left out with a warning. `ai-governance probe`
verifies that each agent really delegates to the scout. The Claude scout sets
`omitClaudeMd: true` (it runs without CLAUDE.md/AGENTS.md instructions, saving tokens); the
Antigravity scout is limited to `view_file`, `grep_search`, `find_by_name`, `list_dir` with
`commandExecutionPolicy: off`. A misspelled tool name can hang an Antigravity subagent, so run
`ai-governance probe --agent antigravity` to verify it after installing.

Codex and Antigravity hooks (`$CODEX_HOME/hooks.json`, `~/.gemini/config/hooks.json`)
are written only after `ai-governance probe --agent <a> --verify` proved that their shell
hooks fire on this machine.

Claude Code user hooks (all through `ai-governance hook claude <event>`, fail-open):

| Event | Effect |
|---|---|
| PreToolUse (Bash) | One-line advice when a deterministic tool replaces the command |
| PostToolUse (Bash) | Output over `threshold_chars` (4000) is replaced by a `ws condense` summary of at most `budget_chars` (2500); `ws log <id>` keeps the full text. Diffs and explicit file reads are never condensed |
| SessionStart | Injects the active task digest (≤ 400 chars) |
| SessionEnd | Logs branch, HEAD and the number of uncommitted files to the active task |
| Stop | Evaluates spend thresholds; a macOS notification is sent only with `"notify_macos": true` in the telemetry config. Never reaches the model |

### Corporate packs

Company-specific, always-on rules and scripts live in `packages/corporate-rules/<company>/` of
the local checkout (gitignored, see [its README](../corporate-rules/README.md)), or wherever
`AI_GOVERNANCE_CORPORATE_DIR` points. Every pack present is installed by the regular
`install --scope user --agent ...`, with no extra flag. Removing or swapping the folder and
installing again removes or swaps its files.

| Pack content | Installed as |
|---|---|
| `rules/<name>.md` | Claude Code: `~/.claude/rules/ai-governance-<company>-<name>.md` (symlink to the source file) |
| | Antigravity: `~/.gemini/config/rules/ai-governance-<company>-<name>.md` (symlink to the same file; its `trigger: always_on` front matter is what Antigravity reads) |
| | Codex: skipped (no per-file global rules), with one warning naming the skipped packs |
| `scripts/*` | Symlinks in `~/.local/bin` (`AI_GOVERNANCE_BIN_DIR`), removed when the last installed agent is uninstalled |

Rules are refreshed only for the agents named in that install: other installed agents keep
the previous pack's rules until they are installed again, so pass every agent you use
(`--agent claude --agent antigravity`). When two packs ship a script with the same name, the
first pack alphabetically wins and the install warns.

### Project scope — `ai-governance install --scope project --agent <...>`

Team policy, committed to the repository:

- Rules for the stacks detected by `ws detect` (e.g. Java rules only in Java repos), written
  once to `.agents/rules/ai-governance-<id>.md` with front matter every agent understands, and
  loaded per file (Claude Code reads them through symlinks in `.claude/rules/`). Without `ws`,
  only the general rules are selected and the install warns.
- One shared `AGENTS.md` block (the only instructions file; for Claude Code projects any
  `CLAUDE.md` or `.claude/CLAUDE.md` is migrated into `AGENTS.md`, because Claude Code ignores
  `AGENTS.md` while a `CLAUDE.md` exists).
- Claude Code `Stop` gate (`ai-governance hook claude stop-gate` in `.claude/settings.json`):
  runs `ws check --changed --cache`, blocking the turn end once with a condensed failure
  summary (≤ 1.5 KB). `gate = false` in the config disables it.
- `.ai-governance/config.toml` (`agents`, `profiles`, `extra_rules`, `excluded_rules`, `gate`,
  plus any tables you add, such as `[design]` for `ws design`) and `.ai-governance/lock.json`
  (ownership ledger). Commit both and the generated files.

### Profiles

Most rules apply automatically once their stack or path is detected. Three groups are opt-in,
enabled per project with `--profile` (only valid with `--scope project`):

| Profile | Covers | Rules |
|---|---|---|
| `architecture` | Clean/hexagonal architecture, DDD, refactoring and strangler fig | `02-clean-architecture-hexagonal`, `03-ddd-domain-modeling`, `10-refactoring-strangler` |
| `distributed` | Event-driven architecture, resilience, concurrency and locking | `07-event-driven-architecture`, `08-resilience-fault-tolerance`, `09-concurrency-locking` |
| `api` | API design and observability | `api-design`, `observability` |

```bash
ai-governance rules profiles                                       # list profiles and their rules
ai-governance install --scope project --profile architecture       # enable a profile
ai-governance uninstall --scope project --profile architecture     # disable it, agents untouched
```

The `architecture` profile also enables the `ws design` layer-boundary check (see
[the workspace README](../workspace/README.md#design-limits-ws-design)), configured via
`[design.layers]` in `.ai-governance/config.toml`.

`ai-governance update` removes the rules of a profile that is no longer enabled and reports a
hint to re-enable it.

## Everyday commands

| Command | Purpose |
|---|---|
| `ai-governance update [--root DIR] [--all] [--check] [--dry-run]` | Re-detect stacks and refresh only the applicable rules; local edits are kept and reported; `--all` covers every registered project; `--check` exits 1 on drift (for CI) |
| `ai-governance uninstall --scope ... --agent ...` | Remove exactly what was written |
| `ai-governance status [--root DIR]` / `doctor [--root DIR]` | What is installed where, per owner (an agent, `project` for the shared rules and `AGENTS.md` block, `corporate` for pack scripts) / read-only health checks (exit 1 on a failing check) |
| `ai-governance agents` | Capability matrix of the supported agents (the table above) |
| `ai-governance budget [--root DIR]` | Fixed context bytes (~tokens) loaded every session, per agent plus a `project` row for the shared rules and `AGENTS.md` block |
| `ai-governance probe --agent <a> [--dir DIR]` then `--verify --seen <tokens>` | Proves on this machine which instruction locations the agent loads and which hooks fire. Codex/Antigravity hooks are installed only after a verified probe |
| `ai-governance rules list` / `rules show <id>` / `rules profiles` | Browse the rule catalog and opt-in profiles |
| `ai-governance progress <subcommand>` | Compact cross-session task state (see below) |
| `ai-governance telemetry <subcommand>` | Local Claude Code spend estimates (see below) |
| `ai-governance jira ...` / `confluence ...` | Atlassian as compact Markdown (`jira` / `confluence` without arguments print their usage) |
| `ai-governance hook <agent> <event>` | Entry point used by the installed hooks |

Installs are idempotent and reversible: an ownership ledger records every file, block and
hook entry; files you edited are never overwritten, foreign files are never replaced
without `--force`, and `--dry-run` shows the exact plan.

### Progress

Tasks are stored in `~/.local/state/ai-governance/progress/`. `show`, `here`, `list` and
`digest` accept `--json`.

| Subcommand | Purpose |
|---|---|
| `list [--all]` | Tasks that are not closed (`--all` includes closed ones) |
| `here [--full]` | Task bound to the current repository/branch |
| `show [<id>] [--full]` | Compact state; `--full` adds the log |
| `new <id> --title "..." [--summary "..."]` | Create a task |
| `close` / `reopen` / `pause <id> [--reason "..."]`, `resume [<id>]` | Change task status |
| `summary <id> "<text>"` | Replace the compact summary |
| `step <id> add\|done\|remove "<text>"` | Plan and tick steps |
| `fact <id> "<text>"` / `note <id> "<text>"` | Record a verified fact / append to the long log |
| `link <id> "<title>" <url>` / `reference <id> <kind> <value> [--url URL]` | Attach links and external references |
| `repo <id> add\|remove [<path>] [--branch B] [--pr N] [--worktree W]` / `sync [<id>]` | Bind repositories / refresh their branches |
| `digest [--id <id>] [--max-chars N]` | Compact context for an agent (default 1600 chars) |

### Telemetry

Estimates come from the Claude Code transcripts on this machine; configuration and caches live
in `~/.local/state/ai-governance/telemetry/` (`config.json`: `monthly_budget_usd`,
`monthly_hard_limit_usd`, `calibration`, `daily_thresholds_pct`, `monthly_thresholds_pct`,
`notify_macos`, `holiday_dates`).

| Subcommand | Purpose |
|---|---|
| `claude-usage [--budget USD] [--spent USD]` | Month-to-date spend vs. the business-day budget pace (for plans whose UI hides spend) |
| `report [--budget USD] [--json]` | Today/month estimate by model, token type and effort; fast-mode calls flagged |
| `thresholds [--notify] [--json]` | Evaluate the daily/monthly alert thresholds (what the Stop hook runs) |
| `calibrate --from DATE --to DATE --actual USD` | Store the ratio between the real spend and the estimate for that period |
| `prices update [--url URL]` | Refresh the cached price table |
| `statusline` | Compact `today $x/allowance · left $y` segment for the Claude Code status line |

## Agent output mode

CLIs print compact plain text when run by an agent, detected from `CLAUDE_CODE_CHILD_SESSION`,
`CLAUDECODE`, `CODEX_SANDBOX` or `ANTIGRAVITY_AGENT`. Override with `AI_GOVERNANCE_AGENT=1|0`.
A plain pipe keeps full human output.

## Configuration and environment

State: `~/.local/state/ai-governance/` (ledger `installed.json`, `progress/`, `telemetry/`,
`probe/`, `frugal/`). Config: `~/.config/ai-governance/` (`frugal.json` with `threshold_chars`
and `budget_chars`; `atlassian.json` with named Atlassian profiles).

| Variable | Effect |
|---|---|
| `AI_GOVERNANCE_STATE_DIR` / `AI_GOVERNANCE_CONFIG_DIR` | Override the state / config locations |
| `XDG_STATE_HOME` / `XDG_CONFIG_HOME` | Base of the default state / config locations (`~/.local/state`, `~/.config`) |
| `AI_GOVERNANCE_AGENT` | Force agent (`1`) or human (`0`) output |
| `CODEX_HOME` | Codex home (default `~/.codex`) |
| `AI_GOVERNANCE_CORPORATE_DIR` | Where corporate packs are read from (default `packages/corporate-rules` of the checkout) |
| `AI_GOVERNANCE_BIN_DIR` | Where corporate pack scripts are linked (default `~/.local/bin`) |
| `FRUGAL=0` or `#nofrugal` in a command | Disable condensing for that command |
| `ATLASSIAN_URL`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` | Default Jira/Confluence credentials |
| `ATLASSIAN_PROFILE` (or `--profile NAME`) | Named profile, read from `ATLASSIAN_PROFILES_FILE`, `~/.config/atlassian/profiles.json` or `atlassian.json`, then from `ATLASSIAN_<NAME>_{URL,EMAIL,API_TOKEN}` |
| `ATLASSIAN_TIMEOUT` | Atlassian request timeout in seconds (default 30) |
