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
`AI_GOVERNANCE_CORPORATE_DIR` at the packs folder). When the corporate root
directory does not exist, previously installed corporate rules and scripts are kept
unchanged and a warning is printed instead of removing them.

## What gets installed where

`install` and `uninstall` take `--scope user|project` (default `project`), one or more
`--agent claude|codex|antigravity` (repeatable), `--root` (project root, default the current
directory), `--dry-run` and, for `install`, `--force`. Without `--agent`, an interactive
terminal asks which agents to use; an agent or a non-interactive shell gets an error instead.
Nothing ever defaults to all agents.

### User scope — `ai-governance install --scope user --agent <claude|codex|antigravity>`

Personal, project-agnostic harness, plus general tool rules and language rules: every catalog rule
marked `user_scope` (always-on general tool rules such as `circleci`, `13-atlassian`, `14-taskflow`,
`15-tool-confidentiality`, `16-git-branch-ownership`, all `2-stacks` rules, the code-level core rules
and `api-design`) is written to the agent's global rules folder with its globs (or always-on trigger),
so it loads in any repository without committing anything. Codex has no per-file global rules: they are
copied to `$CODEX_HOME/ai-governance/`, indexed in `language-rules.md`, and the `AGENTS.md` block
points to that index.

<!-- agents-table:start -->
| | Claude Code | OpenAI Codex | Google Antigravity 2 |
|---|---|---|---|
| Global instructions | ~/.claude/rules/ai-governance.md + language rules (`paths:`) | $CODEX_HOME/AGENTS.md (marker block) + rule indexes in $CODEX_HOME/ai-governance/ | ~/.gemini/config/rules/ai-governance.md (`trigger: always_on`) + language rules (`trigger: glob`) |
| Global hooks | ~/.claude/settings.json (Pre/PostToolUse Bash, SessionStart/End) | $CODEX_HOME/hooks.json PostToolUse condensing (after `probe` verifies) | ~/.gemini/config/hooks.json PreToolUse: raw noisy commands -> `ws run` (after `probe`) |
| Scout subagent | ~/.claude/agents/scout.md (haiku, no web) + researcher.md (sonnet, web research) + runner.md (haiku, Bash, no edits), effort medium | $CODEX_HOME/agents/scout.toml (gpt-6-luna, effort medium, read-only) + config.toml default subagent model gpt-6-luna | ~/.gemini/config/agents/scout.md (model flash, read-only tools, no commands) |
| Skills | ~/.claude/skills/{taskflow,test-audit}/SKILL.md | ~/.agents/skills/{taskflow,test-audit}/SKILL.md | ~/.gemini/config/skills/{taskflow,test-audit}/SKILL.md |
| Project rules | .claude/rules/ai-governance-<id>.md -> symlink to .agents/rules | .agents/rules/ai-governance-<id>.md (shared) | .agents/rules/ai-governance-<id>.md (single source) |
| Rule loading | native `paths:` frontmatter (loaded per file) | injected on edit by a PreToolUse hook (planned) | `trigger: glob` activation (loaded per file; 20k-token rules budget) |
<!-- agents-table:end -->

The read-only `scout` subagent is cross-agent: each agent gets it with a cheap model of its
own provider (Claude `haiku`, Codex `gpt-6-luna`, Antigravity `flash`). Claude splits it in two:
`scout` (`haiku`, no web tools) reads code, and `researcher` (`sonnet`, `WebSearch`/`WebFetch`)
does web research, where comparing and checking sources needs a stronger model. Claude also
gets `runner` (`haiku`, `Bash`/`Read`/`Grep`/`Glob`, no edit tools): it runs noisy commands
(tests, builds, installs, CI logs) and returns only a verdict, the failing names and the first
error lines, so the raw output never reaches the main context. For Codex, a marked block
at the top of `$CODEX_HOME/config.toml` also sets `agents.default_subagent_model = "gpt-6-luna"`
and `agents.default_subagent_reasoning_effort = "medium"`; if the file already defines an
`[agents]` table or those keys, the block is left out with a warning. `ai-governance probe`
verifies that each agent really delegates to the scout. The Claude scout and researcher set
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

### Shell completion (zsh)

Any user install also writes `<TAB>` completion for `ai-governance`, `ws` and `spec` (the
ones on `PATH`) to `~/.local/share/ai-governance/zsh/_<tool>`, and prepends one marked
`fpath=(...)` line to `~/.zshrc` so it is found before `compinit` (oh-my-zsh included).
Subcommands, options and their choices complete with their help text:

```text
$ ai-governance telemetry <TAB>
calibrate     -- Store the ratio between the real spend and the estimate for a period
claude-usage  -- Month-to-date Claude spend vs. business-day budget pace
...
```

The scripts are static (nothing runs on `<TAB>`); `ai-governance update` regenerates them
from each tool's argparse tree, so new commands show up after an update. Open a new shell
to load them. `ai-governance completion zsh [tool]` prints one; skipped without a
`~/.zshrc`; removed with the last uninstalled agent.

### Corporate packs

Company-specific, always-on rules and scripts live in `packages/corporate-rules/<company>/` of
the local checkout (gitignored, see [its README](../corporate-rules/README.md)), or wherever
`AI_GOVERNANCE_CORPORATE_DIR` points. Every pack present is installed by the regular `install --scope user --agent ...`,
with no extra flag. Removing or swapping the folder and installing again removes
or swaps its files. When the corporate root directory does not exist, previously
installed corporate rules and scripts are kept unchanged and the installer prints
a warning explaining how to set `AI_GOVERNANCE_CORPORATE_DIR`. An existing but empty
root, or a pack deselected by config, still removes as normal.

| Pack content | Installed as |
|---|---|
| `rules/<name>.md` | Claude Code: `~/.claude/rules/ai-governance-<company>-<name>.md` (symlink to the source file) |
| | Antigravity: `~/.gemini/config/rules/ai-governance-<company>-<name>.md` (symlink to the same file; its `trigger: always_on` front matter is what Antigravity reads) |
| | Codex: `$CODEX_HOME/ai-governance/company/<company>-<name>.md` (symlink to the same file; the `AGENTS.md` block tells Codex to read them once per session) |
| `scripts/*` | Symlinks in `~/.local/bin` (`AI_GOVERNANCE_BIN_DIR`), removed when the last installed agent is uninstalled |

Rules are refreshed only for the agents named in that install: other installed agents keep
the previous pack's rules until they are installed again, so pass every agent you use
(`--agent claude --agent antigravity`). When two packs ship a script with the same name, the
first pack alphabetically wins and the install warns.

### Personal pack

Personal preferences live outside the repository in `$AI_GOVERNANCE_PERSONAL_DIR` or
`~/.config/ai-governance/personal/` (honouring `AI_GOVERNANCE_CONFIG_DIR`). Every rule
in `<root>/rules/*.md` is installed as a symlink for each selected agent:

| Pack content | Installed as |
|---|---|
| `rules/<name>.md` | Claude Code: `~/.claude/rules/ai-governance-personal-<name>.md` (symlink to the source file) |
| | Antigravity: `~/.gemini/config/rules/ai-governance-personal-<name>.md` (symlink; front matter `trigger: always_on` is what Antigravity reads; no global `GEMINI.md` needed) |
| | Codex: `$CODEX_HOME/ai-governance/personal/<name>.md` (symlink; the `AGENTS.md` block tells Codex to read `personal/` once per session) |

When the personal root directory does not exist, previously installed personal links are kept
unchanged and a warning is printed explaining how to set `AI_GOVERNANCE_PERSONAL_DIR`.
An existing directory with an empty `rules` folder removes previous links as normal.
Uninstalling an agent removes its personal links.

### Generated entry files (Claude Code)

At user scope, Claude Code receives entry files managed via marker blocks:

- `~/.claude/CLAUDE.md`: contains only `@AGENTS.md` (does not @-import individual rules).
- `~/.claude/AGENTS.md`: short text listing the three layers (engine catalog, corporate, personal) and where their files are installed.

Marker blocks never overwrite existing content: user content outside the markers is preserved
byte-for-byte upon install, update, and uninstall. Re-running the install is idempotent.
`ai-governance doctor` checks that both entry blocks are present when Claude is installed at user scope.
For Antigravity, rules with `trigger: always_on` front matter in `~/.gemini/config/rules/` suffice; no global `GEMINI.md` is needed.

### Rule layers and precedence

The engine renders instructions across four layers:

1. **Repository rules**: committed in `.agents/rules/` and project `AGENTS.md`.
2. **Personal pack**: personal preferences in `~/.config/ai-governance/personal/rules/*.md`.
3. **Corporate pack**: company rules in `packages/corporate-rules/<company>/rules/*.md`.
4. **Engine catalog**: general tool rules and path-scoped language rules from the package.

When rules conflict, the precedence order is:
`repo rules > personal pack > corporate pack > engine catalog`. Repo rules always win.

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
| `ai-governance taskflow <subcommand>` | Task tracking and the multi-agent plan/validate/work/judge flow (see below) |
| `ai-governance telemetry <subcommand>` | Local Claude Code spend estimates (`ai-governance telemetry --help`) |
| `ai-governance jira ...` / `confluence ...` | Atlassian as compact Markdown (`jira` / `confluence` without arguments print their usage) |
| `ai-governance hook <agent> <event>` | Entry point used by the installed hooks |

Installs are idempotent and reversible: an ownership ledger records every file, block and
hook entry; files you edited are never overwritten, foreign files are never replaced
without `--force`, and `--dry-run` shows the exact plan.

### Taskflow

One store, `~/.local/state/ai-governance/taskflow/tasks/<ID>/`: `state.json`, the long
`log.md`, `rounds/` (one file per agent call plus `index.md`), `evidence/` and
`friction.md`. It tracks any task (steps, facts, decisions, links) and runs the
TriAgentTaskFlow: `plan -> validate -> work -> judge -> [staging] -> review -> done`, with a
`findings` exit when the branch belongs to someone else. `taskflow --help` is the
operating guide; `taskflow status <id>` lists what is missing for the next phase, which
verdicts and approvals are stale, and the next command.

| Subcommand | Purpose |
|---|---|
| `list [--all]`, `here`, `show [<id>] [--full] [--json]`, `digest` | Read tasks (`here`: bound to this branch/repository) |
| `new <id> --title "..." [--parent P] [--workflow W] [--owner self\|external]` | Create a task or subtask; `switch <id> <sub>` sets the active subtask |
| `summary`, `step add\|done\|remove`, `fact`, `decide --why`, `note`, `link`, `reference`, `friction` | Record what a later session needs |
| `bind <id> --repo P [--integration-branch B] [--pr N]`, `unbind` | Bind repositories/worktrees |
| `stamp <id> [--remote]` | Code stamp of the bound repositories (HEAD + every changed path) and risk by path |
| `round <id> dispatch --role planner\|validator`, `round <id> collect --round N --dispatch-id D`, `round <id> abort` / `round <id> record` | Reserve a reader round and print its Orca worker-start line (the engine never launches an agent), settle it from its worker or abort it / log a round run elsewhere (context only). `round <id> run` is gone: it is a hidden stub that exits 2 and points here |
| `tdd <id> red\|green --cmd "..."`, `tdd <id> skip` | Mandatory test-first evidence; skipping needs the user's approval |
| `judge <id> [--focus F]` | Runs the checks on a throwaway `git worktree` of HEAD, then prints the Orca worker line of every required judge (a reader of the real checkout; settle with `round collect`) |
| `phase <id> <phase>`, `block`/`unblock`, `close [--abandon]` | Move through the gates |
| `approve <id> --action A --target T --user-reply "..." [--consequence "..."]` | Record an approval the user gave in the chat |
| `deploy <id> ...`, `evidence <id> ...` | Record a deployment the user made and evidence bound to its SHA |
| `findings`, `handoff --to <role>`, `draft` | Findings package for another owner, context for a role, ticket draft (secrets scrubbed) |
| `config` | Show and validate `taskflow.toml` |

Configuration: `~/.config/ai-governance/taskflow.toml` (`[roles.planner|validator|builder]`
with `agent`/`model`, `[[judges]]` with `focus`/`agent`/`model` (`[[roles.judges]]` is accepted too, in the user and in the repository file), `[checks] commands`,
`[[risk.rules]]` with `paths`, `judges`, `checks`, `restaging`); a repository's
`.ai-governance/taskflow.toml` can add, replace or disable controls (see Configuration layers). Gates the engine enforces:

- Different agents means different sessions: planner, validator and each judge are separate
  sessions, and the builder is the coordinating session. The validator and every judge must be a
  different provider (`codex` in `codex/gpt-6.1-sol`) than the builder; the planner may share the
  builder's provider. A repository narrows the agents it allows with `[taskflow] allowed_agents`
  in `.ai-governance/config.toml` (the user's set intersected with each bound repo's; malformed
  values block every agent; a role left at its default moves to an allowed agent, an explicit
  choice outside the set is an error). Every required focus must `pass` on
  the current code stamp, and any code change makes verdicts and approvals stale.
- Readers (planner, validator, judge) run with full permissions and a read-only limit in the
  prompt; a reader that changes the tree invalidates its round, and the change is kept.
- Risky approvals (deploy, prod, migration, infra, permissions, delete, policy-downgrade,
  restaging) need the consequence shown, a reply naming action and target, and that reply in
  a real user message of the Claude transcript; production actions are refused after 16:00
  and on Friday after 13:00.

## Configuration and environment

State: `~/.local/state/ai-governance/` (ledger `installed.json`, `taskflow/`, `telemetry/`,
`probe/`, `frugal/`). Data: `~/.local/share/ai-governance/` (`zsh/` completions). Config: `~/.config/ai-governance/`.

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
| `taskflow.planner_agent` | `AI_GOVERNANCE_PLANNER_AGENT` | `antigravity` | Agent of the planner role (user level only: a repo cannot change it) |
| `taskflow.planner_model` | `AI_GOVERNANCE_PLANNER_MODEL` | `gemini-4-argon-high` | Model of the planner role (user level only: a repo cannot change it) |
| `taskflow.validator_agent` | `AI_GOVERNANCE_VALIDATOR_AGENT` | `codex` | Agent of the validator role (user level only: a repo cannot change it) |
| `taskflow.validator_model` | `AI_GOVERNANCE_VALIDATOR_MODEL` | `gpt-6.1-sol` | Model of the validator role (user level only: a repo cannot change it) |
| `taskflow.builder_agent` | `AI_GOVERNANCE_BUILDER_AGENT` | `claude` | Agent of the builder role (user level only: a repo cannot change it) |
| `taskflow.builder_model` | `AI_GOVERNANCE_BUILDER_MODEL` | `""` | Model of the builder role (user level only: a repo cannot change it) |
| `taskflow.judge_agent` | `AI_GOVERNANCE_JUDGE_AGENT` | `codex` | Agent of the judge role (user level only: a repo cannot change it) |
| `taskflow.judge_model` | `AI_GOVERNANCE_JUDGE_MODEL` | `gpt-6.1-sol` | Model of the judge role (user level only: a repo cannot change it) |
| `agents.codex_scout_model` | `AI_GOVERNANCE_CODEX_SCOUT_MODEL` | `gpt-6-luna` | Model of the Codex scout subagent written at install |
| `corporate.packs` | `AI_GOVERNANCE_CORPORATE` | `[]` (all) | Company packs to install, comma separated (empty: every pack present) |
| `atlassian.timeout_seconds` | `ATLASSIAN_TIMEOUT` | `30.0` | HTTP timeout of Jira and Confluence calls |
| `pricing.timeout_seconds` | `AI_GOVERNANCE_PRICING_TIMEOUT_SECONDS` | `10.0` | Timeout of the price feed download |
| `schedule.label` | `AI_GOVERNANCE_SCHEDULE_LABEL` | `com.ai-governance.prices-update` | launchd label of the price-refresh agent |

Role and model settings (`taskflow.<role>_agent|_model`, `agents.*`) are read from
the user level only: a repository cannot swap the agents that run with full permissions.
The `agents.<name>_binary` settings (and `AI_GOVERNANCE_<NAME>_BINARY`) were removed because agents
run as Orca workers: files that still set them keep loading, the value is ignored, and
`config show` lists the key as `no longer used`. Point `ORCA_CLI_COMMAND` at a different Orca CLI instead.
`ai-governance install --scope user --corporate acme,globex` (or `corporate.packs`) installs
only those company packs; an unknown name is an error that lists the packs present. `--corporate ""` (or `AI_GOVERNANCE_CORPORATE=`) installs no pack; choosing nothing installs every pack present.
An environment variable that is set but empty counts as **unset** (a stray `VAR=` never blanks a command, model or timeout); the only exceptions are selections where "nothing" is a real answer: `corporate.packs` (`AI_GOVERNANCE_CORPORATE=` installs no pack) and the gate's `QG_SKIP=` (skip nothing).
`hooks.gate_command` is split like a shell line and its first word looked up on `PATH`.

`taskflow.toml` keeps roles, judges, checks and risk rules. The repository's
`.ai-governance/taskflow.toml` has priority over the user's for these controls: it can add
one, replace one with the same id (a judge `focus`, a risk rule `name`) and switch one off
with a `[disable]` table of ids:

```toml
[disable]
judges = ["performance"]        # judge focuses
checks = ["ws check --changed"] # check commands, verbatim
risk = ["migrations"]           # risk rule names
```

Every judge a repository adds or replaces runs with the user's agent and model
(`taskflow.judge_agent` / `taskflow.judge_model`); `agent`, `model`, `binary` and `command`
fields in the repository file are ignored with a warning.

**A repository's controls need your approval.** Check commands run through a shell with your
permissions, so a repository's `.ai-governance/taskflow.toml` is trusted per repository, like
direnv. The trust is a hash (`v4:`) of that repository's whole parsed file: checks, risk rules
with their `paths` and `checks`, judges, `[disable]` and `timeout_seconds`, with keys sorted and
list order kept. Any file with content (anything beyond empty tables and comments) is **ignored
entirely while it is not trusted**: no adds, no replacements, no `[disable]`, no commands, no
timeout. An untrusted repository therefore cannot remove another repository's control either.
`taskflow status`, `config` and `judge` report `repo config pending trust`, and
`ai-governance config show --origin` lists its controls as `repo (pending trust)`. Any change to
the file (a command, a rule's paths, the order of a list) makes it pending again.
`ai-governance taskflow trust [--repo PATH]` prints the whole control config it approves and the
commands it would run and, after you confirm in a terminal, stores the hash in
`~/.local/state/ai-governance/taskflow/trust.json`. Each repository is trusted on its own,
independent of other repositories and of the user's config, so a task bound to several
repositories applies all the approved ones. It needs stdin and stdout on a terminal even with
`--yes` and refuses when an agent variable (`CLAUDECODE`, `CODEX_*`, `CLAUDE_CODE_*`, ...) is
present, whatever `AI_GOVERNANCE_AGENT` says. Entries of older schemes (`v1`-`v3`) are simply
pending again.

A task's first approval starts from the user's own policy, so whatever a repository
disables before the first stamp is listed as a policy reduction too; what a trusted repository
disables or weakens relative to the user's policy plus the repositories before it is a
reduction as well, until a `policy-downgrade` approval acknowledges it. `ai-governance config show --origin`
lists them as `taskflow.judge.<focus>`, `taskflow.check.<command>` and `taskflow.risk.<name>`
with `user`, `default` or `repo (added|replaced|disabled)`. Removing controls counts as a
policy reduction for `taskflow` approvals. Of its scalars only `timeout_seconds` follows the precedence above; `workflow` and the
roles stay user-owned. An unknown `--profile` for Jira/Confluence is now an error that lists the known profiles.

| Variable | Effect |
|---|---|
| `AI_GOVERNANCE_STATE_DIR` / `AI_GOVERNANCE_CONFIG_DIR` / `AI_GOVERNANCE_DATA_DIR` | Override the state / config / data locations |
| `AI_GOVERNANCE_LAUNCH_AGENTS_DIR` | Override the LaunchAgents folder (launchctl is then not called) |
| `XDG_STATE_HOME` / `XDG_CONFIG_HOME` / `XDG_DATA_HOME` | Base of the default locations (`~/.local/state`, `~/.config`, `~/.local/share`) |
| `ZDOTDIR` | Where `.zshrc` is looked up for completions (default `~`) |
| `AI_GOVERNANCE_AGENT` | Force agent (`1`) or human (`0`) output |
| `CODEX_HOME` | Codex home (default `~/.codex`) |
| `AI_GOVERNANCE_CORPORATE_DIR` | Where corporate packs are read from (default `packages/corporate-rules` of the checkout) |
| `AI_GOVERNANCE_BIN_DIR` | Where corporate pack scripts are linked (default `~/.local/bin`) |
| `FRUGAL=0` or `#nofrugal` in a command | Disable condensing for that command |
| `ATLASSIAN_URL`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN` | Default Jira/Confluence credentials |
| `ATLASSIAN_PROFILE` (or `--profile NAME`) | Named profile, read from `ATLASSIAN_PROFILES_FILE`, `~/.config/atlassian/profiles.json` or `atlassian.json`, then from `ATLASSIAN_<NAME>_{URL,EMAIL,API_TOKEN}` |
| `ATLASSIAN_TIMEOUT` | Atlassian request timeout in seconds (default 30) |
