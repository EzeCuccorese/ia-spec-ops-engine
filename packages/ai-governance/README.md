# ai-governance

Per-agent engineering standards, token frugality and lightweight task tracking for AI coding
agents. Supported agents: **Claude Code**, **OpenAI Codex** and **Google Antigravity 2**. The
installer is a deterministic CLI: you choose the agent(s), and only those agents' files are
touched.

Deterministic execution (stack detection, quality gates, condensed command output, Git
hooks) lives in the sibling `workspace` package (`ws`); `ai-governance` calls it through
versioned `--json` contracts and degrades gracefully when it is missing.

## Install

Step-by-step walkthrough with verification: [docs/getting-started.md](../../docs/getting-started.md).

```bash
uv tool install ./packages/ai-governance   # CLI: ai-governance
uv tool install ./packages/workspace       # CLI: ws (recommended)
```

Corporate packs are read from `~/.config/ai-governance/corporate-rules/` or the external
directory selected by `AI_GOVERNANCE_CORPORATE_DIR`. Corporate content is never stored in this
checkout or included in a package. Third-party skills in `skills/` are versioned separately.
Install with `uv tool install --editable ./packages/ai-governance` when
you use checkout-local skills. When the corporate root directory does not exist, previously
installed corporate rules and scripts are kept unchanged and a warning is printed instead of
removing them.

## What gets installed where

`install` and `uninstall` take `--scope user|project` (default `project`), one or more
`--agent claude|codex|antigravity` (repeatable), `--root` (project root, default the current
directory), `--dry-run` and, for `install`, `--force`. Without `--agent`, the command exits
with an error requiring you to choose the agent(s) explicitly; nothing ever defaults to all
agents.

### User scope — `ai-governance install --scope user --agent <claude|codex|antigravity>`

Global, project-agnostic harness, plus general tool rules and language rules: every non-profiled
catalog rule marked `user_scope` (always-on general tool rules such as `circleci`, `deploy-approvals`,
`production-risk-window`, `13-atlassian`, `14-taskflow`, `15-tool-confidentiality`,
`16-git-branch-ownership`, `17-quality-gate`, `18-surgical-changes`, `19-pull-requests`,
`20-review-ready-code`, `21-antigravity-routing`, `22-user-communication`, all `2-stacks` rules and the code-level core rules) is written to the agent's
global rules folder with its globs (or always-on trigger), so it loads in any repository without
committing anything. Opt-in profile rules (`architecture`, `distributed`, `api`) remain project-scoped.
Always-on user-scope rules are not duplicated into project scope unless forced via `extra_rules`. Codex
has no per-file global rules: they are copied to `$CODEX_HOME/ai-governance/`, indexed in
`language-rules.md`, and the `AGENTS.md` block points to that index.

<!-- agents-table:start -->
| | Claude Code | OpenAI Codex | Google Antigravity 2 |
|---|---|---|---|
| Global instructions | ~/.claude/rules/ai-governance.md + language rules (`paths:`) | $CODEX_HOME/AGENTS.md (marker block) + rule indexes in $CODEX_HOME/ai-governance/ | ~/.gemini/config/rules/ai-governance.md (`trigger: always_on`) + language rules (`trigger: glob`) |
| Global hooks | ~/.claude/settings.json (Pre/PostToolUse Bash, SessionStart/End) | $CODEX_HOME/hooks.json SessionStart, PostToolUse condensing | ~/.gemini/config/hooks.json SessionStart, PreToolUse: raw noisy commands -> `ws run` |
| Scout subagent | ~/.claude/agents/scout.md (haiku, no web) + researcher.md (sonnet, web research) + runner.md (haiku, Bash, no edits), effort medium | $CODEX_HOME/agents/scout.toml (gpt-6-luna, no web) + researcher.toml (gpt-6.2-sol, web research) + runner.toml (gpt-6-luna, read-only), effort medium + config.toml default subagent model gpt-6-luna | ~/.gemini/config/agents/scout.md (flash, no web) + researcher.md (pro, web research) + runner.md (flash, run_command, no edits) |
| Skills | ~/.claude/skills/{taskflow,test-audit,code-simplifier,slack-formatting}/SKILL.md | ~/.agents/skills/{taskflow,test-audit,code-simplifier,slack-formatting}/SKILL.md | ~/.gemini/config/skills/{taskflow,test-audit,code-simplifier,slack-formatting}/SKILL.md |
| Project rules | .claude/rules/ai-governance-<id>.md -> symlink to .agents/rules | .agents/rules/ai-governance-<id>.md (shared) | .agents/rules/ai-governance-<id>.md (single source) |
| Rule loading | native `paths:` frontmatter (loaded per file) | injected on edit by a PreToolUse hook (planned) | `trigger: glob` activation (loaded per file; 20k-token rules budget) |
<!-- agents-table:end -->

The read-only `scout`, `researcher`, and `runner` subagents are installed across all three agents with
each provider's corresponding model tier: `scout` reads code (`haiku` / `gpt-6-luna` / `flash`),
`researcher` handles web research where comparing and checking sources needs a stronger model
(`sonnet` / `gpt-6.2-sol` / `pro`), and `runner` runs noisy commands (tests, builds, installs, CI
logs) and returns only a verdict, failing names, and first error lines (`haiku` / `gpt-6-luna` /
`flash`). For Codex, a marked block at the top of `$CODEX_HOME/config.toml` also sets
`agents.default_subagent_model = "gpt-6-luna"` and `agents.default_subagent_reasoning_effort = "medium"`;
if the file already defines an `[agents]` table or those keys, the block is left out with a warning.
The Claude subagents set `omitClaudeMd: true` (it runs without CLAUDE.md/AGENTS.md instructions, saving
tokens); the Antigravity subagents set `subagent: true` and `mainAgent: false` and restrict tools
(`view_file`, `grep_search`, `find_by_name`, `list_dir` with `commandExecutionPolicy: off` for
`scout`; `view_file`, `search_web` for `researcher`; `run_command` added with
`commandExecutionPolicy: auto` for `runner`).

Claude Code user hooks (all through `ai-governance hook claude <event>`, fail-open):

| Event | Effect |
|---|---|
| PreToolUse (Bash) | One-line advice when a deterministic tool replaces the command |
| PostToolUse (Bash) | Output over `threshold_chars` (4000) is replaced by a `ws condense` summary of at most `budget_chars` (2500); `ws log <id>` keeps the full text. Diffs and explicit file reads are never condensed |
| SessionStart | Injects the active task digest (≤ 400 chars) |
| SessionEnd | Logs branch, HEAD and the number of uncommitted files to the active task |

### Corporate packs

Company-specific, always-on rules, scripts and skills live outside Git, by default in
`~/.config/ai-governance/corporate-rules/<company>/` (or git-ignored under
`config/ai-governance/corporate-rules/<company>/` for an editable checkout; see
[the corporate pack guide](../corporate-rules/README.md)), or wherever
`AI_GOVERNANCE_CORPORATE_DIR` points.
Every pack present is installed by the regular `install --scope user --agent ...`, with no extra
flag. Removing or swapping the folder and installing again removes or swaps its files. When the
corporate root directory does not exist, previously installed corporate rules and scripts are kept
unchanged and the installer prints a warning explaining how to set `AI_GOVERNANCE_CORPORATE_DIR`.
An existing but empty root, or a pack deselected by config, still removes as normal.

| Pack content | Installed as |
|---|---|
| `rules/<name>.md` | Claude Code: `~/.claude/rules/ai-governance-<company>-<name>.md` (symlink to the source file) |
| | Antigravity: `~/.gemini/config/rules/ai-governance-<company>-<name>.md` (symlink to the same file; its `trigger: always_on` front matter is what Antigravity reads) |
| | Codex: `$CODEX_HOME/ai-governance/company/<company>-<name>.md` (symlink to the same file; the `AGENTS.md` block tells Codex to read them once per session) |
| `scripts/*` | Symlinks in `~/.local/bin` (`AI_GOVERNANCE_BIN_DIR`), removed when the last installed agent is uninstalled |
| `skills/<name>/` | Managed directory copies in `~/.claude/skills/<name>`, `~/.agents/skills/<name>` (Codex) and `~/.gemini/config/skills/<name>` (Antigravity) |

Rules are refreshed only for the agents named in that install: other installed agents keep
the previous pack's rules until they are installed again, so pass every agent you use
(`--agent claude --agent antigravity`). When two packs ship a script with the same name, the
first pack alphabetically wins and the install warns.

### Skills

A third-party skill is a directory (`SKILL.md` plus optional scripts) that lives in one source
directory and is copied into every installed agent as a managed directory copy tracked in the
ownership ledger (agents such as Antigravity cannot read skill files across symlinks outside
their config directory). Sources:

- **Third-party skills (versioned in git):** `skills/<name>/` at the repository root.
- **Corporate skills (private, outside this checkout):**
  `$AI_GOVERNANCE_CORPORATE_DIR/<pack>/skills/<name>/`.

Names must be unique across bundled, corporate and third-party skills. A collision is an error. Copies
go to `~/.claude/skills/<name>`, `~/.agents/skills/<name>` (Codex) and
`~/.gemini/config/skills/<name>` (Antigravity). Edit a skill in its source directory and run
`ai-governance skills sync` to propagate updates. Locally edited copies and foreign entries are
never overwritten silently (`--force` replaces them); `ai-governance doctor` warns when a copy is
`outdated` or `edited`. `install`, `sync` and `uninstall` keep the copies in step with the ledger.
Externally managed entries (`synced` and Orca skills: `orchestration`, `orca-cli`,
`orca-computer-use`, `computer-use`) are ignored and cannot be added or migrated.

```
ai-governance skills list                                  # source, path and synced/outdated/edited/missing/foreign per agent
ai-governance skills add <dir> [--name N]                  # copy into skills/, then sync to agents
ai-governance skills rm <name>                             # personal skills only: delete from skills/ and remove copies
ai-governance skills sync [--force]                        # reconcile managed copies for every source
ai-governance skills migrate [--dry-run] [--pack P] [--from PATH] [name ...]  # adopt skills already in agent dirs
```

`migrate` scans `~/.claude/skills`, `~/.agents/skills`, `~/.codex/skills` and `~/.gemini/config/skills`, follows (possibly
relative) symlinks to the real directory, moves it into `skills/` (or `<pack>/skills/` with
`--pack`), deletes the other copies and old links, and creates managed copies in each installed
agent. If real copies differ it changes nothing for that name unless `--from` picks one.

### Generated entry files (Claude Code)

At user scope, Claude Code receives entry files managed via marker blocks:

- `~/.claude/CLAUDE.md`: contains only `@AGENTS.md` (does not @-import individual rules).
- `~/.claude/AGENTS.md`: short text pointing to the engine catalog and the active private company rules.

Marker blocks never overwrite existing content: user content outside the markers is preserved
byte-for-byte upon install, update, and uninstall. Re-running the install is idempotent.
`ai-governance doctor` checks that both entry blocks are present when Claude is installed at user scope.
For Antigravity, rules with `trigger: always_on` front matter in `~/.gemini/config/rules/` suffice; no global `GEMINI.md` is needed.

### Rule sources

- **Engine catalog:** versioned, general engineering and agent-workflow rules shared across
  repositories. Model routing and effort guidance for Antigravity are defined here.
- **Repository rules:** project-specific instructions committed with the project. They can add
  detail for the repository and must preserve the confidentiality requirements of the catalog.
- **Corporate packs:** private company policies loaded from an external directory. They must
  never be stored in the checkout, included in packages, or exposed in another company's scope.

The engine catalog supplies the global rules. Repository and active corporate rules add
scope-specific requirements. Corporate artifacts must never identify the engine or its tools.

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
`[design.layers]` in the unified workspace config files (user global, in-repo `.workspace/config.toml`,
or personal per-repo `~/.config/workspace/repos/<repo-name>.toml`).

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
| `ai-governance rules list` / `rules show <id>` / `rules profiles` | Browse the rule catalog and opt-in profiles |
| `ai-governance skills <subcommand>` | Keep each third-party skill in one source directory and copy it into Claude, Codex and Antigravity (see above) |
| `ai-governance taskflow <subcommand>` | Task notebook and multi-provider design debates across agents (see below) |
| `ai-governance brain <subcommand>` | Cross-agent second brain notes (`add`, `list`, `show`, `edit`, `search`, `archive`, `import`; see below) |
| `ai-governance ui <start\|stop\|status\|open>` | Local visual dashboard for Taskflow and Second Brain (`127.0.0.1:7474`; see below) |
| `ai-governance pr-watch <status\|check>` | Read-only GitHub PR watcher (`ready_to_merge`, comments, CI failures, conflicts) |
| `ai-governance slack-notify --channel ...` | Allowlist-guarded Slack Markdown notifier using a local Bot Token |
| `ai-governance jira ...` / `confluence ...` | Atlassian as compact Markdown (`jira` / `confluence` without arguments print their usage) |
| `ai-governance hook <agent> <event>` | Entry point used by the installed hooks |

Installs are idempotent and reversible: an ownership ledger records every file, block and
hook entry; files you edited are never overwritten, foreign files are never replaced
without `--force`, and `--dry-run` shows the exact plan.

### Taskflow

One store, `~/.local/state/ai-governance/taskflow/tasks/<ID>/`: `state.json`, the long
`log.md`, `rounds/` (one file per debate round plus `index.md`), `evidence/` and
`friction.md`. It serves as a persistent task notebook for multi-session work (steps,
facts, decisions, links, approvals) and runs multi-provider design debates through Orca
workers. `taskflow --help` is the operating guide; `taskflow status <id>` shows the
task state, open steps, and debate status.

| Subcommand | Purpose |
|---|---|
| `list [--all]`, `here`, `show [<id>] [--full] [--json]`, `digest` | Read tasks (`here`: bound to this branch/repository) |
| `new <id> --title "..." [--parent P]` | Create a task or subtask; `switch <id> <sub>` sets the active subtask |
| `summary`, `step add\|done\|remove`, `fact`, `decide --why`, `note`, `link`, `reference`, `friction` | Record what a later session needs |
| `bind <id> --repo P [--integration-branch B] [--pr N]`, `unbind` | Bind repositories/worktrees |
| `stamp <id> [--remote]` | Code stamp of the bound repositories (HEAD + every changed path) |
| `debate <id> open --topic-file F --agents a,b [--model a=m] [--web] [--artifact P]`, `debate <id> cross`, `debate <id> status`, `debate <id> close [--partial]` | Run a multi-provider design debate: open independent thesis rounds, run all-against-all cross-examination rounds, inspect seat state, or write `synthesis.md` (and record open points as steps) |
| `round <id> collect --round N --dispatch-id D`, `round <id> abort` | Settle or abort a dispatched debate worker round |
| `close [--abandon]`, `block`/`unblock` | Close or pause a task |
| `approve <id> --action A --target T --user-reply "..." [--consequence "..."]` | Record an approval the user gave in the chat |
| `deploy <id> ...`, `evidence <id> ...` | Record a deployment the user made and evidence bound to its SHA |
| `config` | Show and validate `taskflow.toml` |

Risky approvals (deploy, prod, migration, infra, permissions, delete, policy-downgrade,
restaging) require the consequence to be shown and a reply explicitly naming action and target
(recorded as declared); production actions are refused after 16:00 and on Friday after 13:00.

### Second brain

`ai-governance brain` manages cross-agent notes (PARA Resources and Archive) outside the
repository. Notes are organized by scope (`global`, `repo`, or `company`) and protected by a
secret guard that rejects secret-like content on write.

| Subcommand | Purpose |
|---|---|
| `add` | Capture a new note (rejects secret-like content) |
| `list` | List notes with optional filters |
| `show <slug>` | Show a note by slug or `<scope>/<slug>` |
| `edit <slug>` | Open an existing note in `$VISUAL` / `$EDITOR` |
| `search <query>` | Search brain notes, taskflow tasks, and rules |
| `archive <task-id>` | Write an idempotent archive note from a taskflow task |
| `import` | Curated, deduplicated import from Claude or Codex memory |

### Visual dashboard

`ai-governance ui` serves a local FastAPI + React dashboard for browsing and managing Taskflow
tasks, multi-provider debates, and the Second Brain neural-network knowledge graph:

```bash
ai-governance ui start [--background] [--host 127.0.0.1] [--port 7474]
ai-governance ui status [--json]
ai-governance ui open [--orca]       # open in system browser or Orca embedded browser
ai-governance ui stop
```

The server binds strictly to loopback (`127.0.0.1`, `localhost`, or `::1`), validates `Host` and
`Origin` headers, and protects all mutating routes with a per-session `X-UI-Token` injected into
the served HTML. Background daemon state (`server.pid`, `server.json`, `server.log`) lives under
`~/.local/state/ai-governance/ui/`. Launching debate workers from the UI only runs sealed
`worker-start` commands verified against Taskflow's SHA-256 dispatch seals.

### Upgrading from retired personal rules

If you previously used personal rules, your retained personal source directory is left untouched.
Copy any custom rules you want to keep into each agent's supported instructions directory
(`~/.claude/rules/`, `~/.gemini/config/rules/`, or `$CODEX_HOME/AGENTS.md`).

### PR watcher

`ai-governance pr-watch check` reports new comments, CI failures and conflicts on your open PRs.
Noise filters for `new_comment` alerts:

- `--ignore-authors login1,login2` (repeatable) skips comments from those logins.
- `--ignore-draft-bots` skips comments from bot accounts (`[bot]` suffix or GitHub `Bot` type) while the PR is a draft.

## Configuration and environment

State: `~/.local/state/ai-governance/` (ledger `installed.json`, `taskflow/`, `frugal/`).
Config: `~/.config/ai-governance/` (or `<checkout>/config/ai-governance/` when installed editable and present, git-ignored).

### Configuration layers

Every setting resolves the same way, lowest to highest priority:
**default < user (`~/.config/ai-governance/config.toml`) < repo (`<repo>/.ai-governance/config.toml`) < environment variable < CLI flag**.
Files are TOML (`[frugality]` / `threshold_chars = 4000`). Older JSON files keep working
(`config.json`, `frugal.json`; a one-line notice is printed on a terminal, never in agent mode).
`ai-governance config show [--origin] [--json]` prints the effective values and the layer
(plus file or variable) each one came from.

| Key | Env var | Default | Meaning |
|---|---|---|---|
| `frugality.threshold_chars` | `AI_GOVERNANCE_FRUGAL_THRESHOLD_CHARS` | `4000` | Shell output longer than this is condensed |
| `frugality.budget_chars` | `AI_GOVERNANCE_FRUGAL_BUDGET_CHARS` | `2500` | Size the condensed output is cut down to |
| `frugality.condense_timeout_seconds` | `AI_GOVERNANCE_FRUGAL_TIMEOUT_SECONDS` | `30` | Timeout of the `ws condense` call |
| `output.max_lines` | `AI_GOVERNANCE_OUTPUT_MAX_LINES` | `20` | Lines before output is cut |
| `output.max_chars` | `AI_GOVERNANCE_OUTPUT_MAX_CHARS` | `1500` | Characters before output is cut |
| `hooks.gate_command` | `AI_GOVERNANCE_GATE_COMMAND` | `ws check --changed --cache --json` | Command of the turn-end quality gate (`--budget N` is appended) |
| `hooks.gate_budget_chars` | `AI_GOVERNANCE_GATE_BUDGET_CHARS` | `1500` | Size of the failure summary the gate reports |
| `hooks.gate_timeout_seconds` | `AI_GOVERNANCE_GATE_TIMEOUT_SECONDS` | `900` | Timeout of the turn-end quality gate |
| `taskflow.timeout_seconds` | `AI_GOVERNANCE_CHECK_TIMEOUT_SECONDS` | `1800` | Timeout of each check, judge and TDD command |
| `taskflow.allowed_agents` | `AI_GOVERNANCE_ALLOWED_AGENTS` | `antigravity, codex, claude` | Agents taskflow may use, comma separated (user level; a repo's `.ai-governance/config.toml` `[taskflow] allowed_agents` can only narrow it) |
| `taskflow.denied_models` | `AI_GOVERNANCE_DENIED_MODELS` | `[]` | Models taskflow must never launch, comma separated (a repo file can only add to it) |
| `taskflow.planner_agent` | `AI_GOVERNANCE_PLANNER_AGENT` | `antigravity` | Agent of the planner role (user level only: a repo cannot change it) |
| `taskflow.planner_model` | `AI_GOVERNANCE_PLANNER_MODEL` | `gemini-4-neon-high` | Model of the planner role (user level only: a repo cannot change it) |
| `taskflow.planner_effort` | `AI_GOVERNANCE_PLANNER_EFFORT` | `""` | Effort of the planner role (user level only: a repo cannot change it) |
| `taskflow.validator_agent` | `AI_GOVERNANCE_VALIDATOR_AGENT` | `codex` | Agent of the validator role (user level only: a repo cannot change it) |
| `taskflow.validator_model` | `AI_GOVERNANCE_VALIDATOR_MODEL` | `gpt-6.2-sol` | Model of the validator role (user level only: a repo cannot change it) |
| `taskflow.validator_effort` | `AI_GOVERNANCE_VALIDATOR_EFFORT` | `""` | Effort of the validator role (user level only: a repo cannot change it) |
| `taskflow.builder_agent` | `AI_GOVERNANCE_BUILDER_AGENT` | `claude` | Agent of the builder role (user level only: a repo cannot change it) |
| `taskflow.builder_model` | `AI_GOVERNANCE_BUILDER_MODEL` | `""` | Model of the builder role (user level only: a repo cannot change it) |
| `taskflow.builder_effort` | `AI_GOVERNANCE_BUILDER_EFFORT` | `""` | Effort of the builder role (user level only: a repo cannot change it) |
| `taskflow.judge_agent` | `AI_GOVERNANCE_JUDGE_AGENT` | `codex` | Agent of the judge role (user level only: a repo cannot change it) |
| `taskflow.judge_model` | `AI_GOVERNANCE_JUDGE_MODEL` | `gpt-6.2-sol` | Model of the judge role (user level only: a repo cannot change it) |
| `taskflow.judge_effort` | `AI_GOVERNANCE_JUDGE_EFFORT` | `""` | Effort of the judge role (user level only: a repo cannot change it) |
| `taskflow.debater_agent` | `AI_GOVERNANCE_DEBATER_AGENT` | `codex` | Agent of the debater role (user level only: a repo cannot change it) |
| `taskflow.debater_model` | `AI_GOVERNANCE_DEBATER_MODEL` | `gpt-6.2-sol` | Model of the debater role (user level only: a repo cannot change it) |
| `taskflow.debater_effort` | `AI_GOVERNANCE_DEBATER_EFFORT` | `""` | Effort of the debater role (user level only: a repo cannot change it) |
| `agents.codex_scout_model` | `AI_GOVERNANCE_CODEX_SCOUT_MODEL` | `gpt-6-luna` | Model of the Codex scout subagent written at install |
| `agents.codex_researcher_model` | `AI_GOVERNANCE_CODEX_RESEARCHER_MODEL` | `gpt-6.2-sol` | Model of the Codex researcher subagent written at install |
| `risk_window.cutoff_hour` | `AI_GOVERNANCE_RISK_WINDOW_CUTOFF_HOUR` | `16` | Cutoff hour (0-23) of the production risk window, Monday to Thursday |
| `risk_window.friday_cutoff_hour` | `AI_GOVERNANCE_RISK_WINDOW_FRIDAY_CUTOFF_HOUR` | `13` | Cutoff hour (0-23) of the production risk window on Friday |
| `deploy_approvals.production` | `AI_GOVERNANCE_DEPLOY_APPROVALS_PRODUCTION` | `never` | Production deploy approval policy (`never` or `explicit`) |
| `slack.channel` | `AI_GOVERNANCE_SLACK_CHANNEL` | `""` | Default target of `slack-notify` (user config only) |
| `slack.dm` | `AI_GOVERNANCE_SLACK_DM` | `""` | Target used by `slack-notify --channel dm` |
| `slack.allow` | `AI_GOVERNANCE_SLACK_ALLOW` | `[]` | Allowed Slack channel/user IDs of `slack-notify` |
| `slack.token_env` | `AI_GOVERNANCE_SLACK_TOKEN_ENV` | `SLACK_BOT_TOKEN` | Env var holding the Slack token |
| `slack.keychain_service` | `AI_GOVERNANCE_SLACK_KEYCHAIN_SERVICE` | `""` | macOS Keychain service fallback for the token |
| `slack.bot_name` | `AI_GOVERNANCE_SLACK_BOT_NAME` | `""` | Bot display name (informational only) |
| `corporate.packs` | `AI_GOVERNANCE_CORPORATE` | `[]` (all) | Company packs to install, comma separated (empty: every pack present) |
| `atlassian.timeout_seconds` | `ATLASSIAN_TIMEOUT` | `30.0` | HTTP timeout of Jira and Confluence calls |

Role and model settings (`taskflow.<role>_agent|_model`, `agents.*`) are read from
the user level only: a repository cannot swap the agents that run with full permissions.
The `agents.<name>_binary` settings (and `AI_GOVERNANCE_<NAME>_BINARY`) were removed because agents
run as Orca workers: files that still set them keep loading, the value is ignored, and
`config show` lists the key as `no longer used`. Point `ORCA_CLI_COMMAND` at a different Orca CLI instead.
`ai-governance install --scope user --corporate acme,globex` (or `corporate.packs`) installs
only those company packs; an unknown name is an error that lists the packs present. `--corporate ""` (or `AI_GOVERNANCE_CORPORATE=`) installs no pack; choosing nothing installs every pack present.
An environment variable that is set but empty counts as **unset** (a stray `VAR=` never blanks a command, model or timeout); the only exceptions are selections where "nothing" is a real answer: `corporate.packs` (`AI_GOVERNANCE_CORPORATE=` installs no pack) and the gate's `QG_SKIP=` (skip nothing).
`hooks.gate_command` is split like a shell line and its first word looked up on `PATH`.

User `taskflow.toml` configures default roles (`[roles]` / `taskflow.<role>_agent|_model|_effort`)
and `denied_models`. A repository's `.ai-governance/config.toml` can narrow `allowed_agents`
and add entries to `denied_models` (also additive via `.ai-governance/taskflow.toml`), but
repositories can never weaken user restrictions or execute shell commands from `taskflow.toml`
(no `trust.json` approval step is needed).
An unknown `--profile` for Jira/Confluence is an error that lists the known profiles.

| Variable | Effect |
|---|---|
| `AI_GOVERNANCE_STATE_DIR` / `AI_GOVERNANCE_CONFIG_DIR` / `AI_GOVERNANCE_DATA_DIR` | Override the state / config / data locations |
| `XDG_STATE_HOME` / `XDG_CONFIG_HOME` / `XDG_DATA_HOME` | Base of the default locations (`~/.local/state`, `~/.config`, `~/.local/share`) |
| `AI_GOVERNANCE_AGENT` | Force agent (`1`) or human (`0`) output |
| `CODEX_HOME` | Codex home (default `~/.codex`) |
| `AI_GOVERNANCE_CORPORATE_DIR` | External corporate pack directory (default `~/.config/ai-governance/corporate-rules`) |
| `AI_GOVERNANCE_PERSONAL_DIR` | Legacy override for third-party skill sources only, with `<dir>/skills/` |
| `AI_GOVERNANCE_BIN_DIR` | Where corporate pack scripts are linked (default `~/.local/bin`) |
| `FRUGAL=0` or `#nofrugal` in a command | Disable condensing for that command |
| `ATLASSIAN_URL`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` | Default Jira/Confluence credentials |
| `ATLASSIAN_PROFILE` (or `--profile NAME`) | Named profile, read from `ATLASSIAN_PROFILES_FILE`, `~/.config/atlassian/profiles.json` or `atlassian.json`, then from `ATLASSIAN_<NAME>_{URL,EMAIL,API_TOKEN}` |
| `ATLASSIAN_TIMEOUT` | Atlassian request timeout in seconds (default 30) |
