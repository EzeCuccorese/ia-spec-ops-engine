# Getting started: install, verify and understand ai-governance + ws

This guide installs both CLIs, sets up one agent globally and one repository, and verifies
every piece. Each step says **what it does**, **what changes on disk** and **what you should
see**. Nothing is installed for an agent you do not name with `--agent`.

- `ai-governance` connects agents: instructions, per-stack rules, hooks, a cheap `scout`
  subagent, progress tracking and Claude spend telemetry.
- `ws` (package `workspace`) executes deterministic work: stack detection, quality gates,
  Git hooks and condensed command output.

Every install is recorded in an ownership ledger, so `--dry-run` shows the exact plan, a
second run changes nothing, files you edited are never overwritten, and `uninstall`
restores what was there before.

## 0. Prerequisites

| Tool | Why | Check |
|---|---|---|
| `uv` | Installs both CLIs in isolated environments | `uv --version` |
| Git with config-based hooks | The quality gate uses `hook.<name>.command` | `git hook list pre-push` must not say "unknown command" |
| `jq` (optional) | Only to inspect JSON files in this guide | `jq --version` |
| `gitleaks` (optional) | Secret scanning in pre-commit/pre-push | `gitleaks version` |

## 1. Install the CLIs

```bash
uv tool uninstall ai-governance; uv tool uninstall workspace   # removes older versions and their binaries
uv tool install --force ./packages/ai-governance               # from the repository root
uv tool install --force ./packages/workspace
ai-governance --help
ws --help
```

- **What it does**: installs two binaries in `~/.local/bin`: `ai-governance` and `ws`.
  Older versions exposed eight scripts (`specops`, `governance`, `rules`, `frugal`,
  `telemetry`, `progress`, `jira`, `confluence`); uninstalling first removes them.
- **Expect**: both `--help` outputs list their subcommands. This command must print nothing:
  `ls ~/.local/bin | grep -E '^(specops|governance|rules|frugal|telemetry|progress|jira|confluence)$'`.
- Nothing is configured yet for any agent.

## 2. User scope (global) for one agent

```bash
ai-governance install --scope user --agent claude --dry-run    # the plan, writes nothing
ai-governance install --scope user --agent claude
ai-governance status
```

What gets written for Claude Code:

| File | Purpose | Loaded into the model? |
|---|---|---|
| `~/.claude/rules/ai-governance.md` | ≤1 KB of global instructions: prefer `ws`/`ai-governance` tools, frugal reads, delegation to `scout` | Yes, every session |
| `~/.claude/agents/scout.md` | Read-only subagent on `sonnet`, effort `medium`, for exploration, reading, summaries and web research | Only its name and description |
| `~/.claude/skills/progress/SKILL.md` | How to use the progress tracker | Only its name and description |
| `~/.claude/settings.json` (merged) | Five hooks: `PreToolUse`/`PostToolUse` (Bash), `Stop`, `SessionStart`, `SessionEnd`, all as `ai-governance hook claude <event>` | Only what each hook returns (see below) |
| `~/.local/state/ai-governance/installed.json` | Ownership ledger and the list of projects you install | No |

What each Claude hook does:

| Event | Effect |
|---|---|
| PreToolUse (Bash) | One-line advice when a deterministic tool replaces the command (for example `git worktree add` → `ws worktree`) |
| PostToolUse (Bash) | Output over 4,000 characters is replaced by a `ws condense` summary (about 600 tokens). The full text is kept and read with `ws log <id>`. Diffs and explicit file reads are never condensed |
| SessionStart | Injects up to 400 characters about the task bound to this repository/branch |
| SessionEnd | Appends branch, HEAD and the number of uncommitted files to that task's log |
| Stop | Spend threshold alerts through a macOS notification; nothing reaches the model |

Other agents (`--agent codex`, `--agent antigravity`) get the same pieces in their own
locations; run `ai-governance agents` for the matrix. Codex also gets
`agents.default_subagent_model = "terra"` in a marked block at the top of
`~/.codex/config.toml`. Their output hooks are only installed after step 8 verifies them.

**Check**:

```bash
cat ~/.claude/rules/ai-governance.md
jq '.hooks | keys' ~/.claude/settings.json      # includes PostToolUse, PreToolUse, SessionEnd, SessionStart, Stop
ai-governance install --scope user --agent claude   # second run: "No changes."
```

## 3. Project scope (one repository)

Use a throwaway repository the first time. **Never run steps 3–6 inside the ai-governance
checkout itself**: they create commits and overwrite `pyproject.toml`. Every block below
starts with `cd /tmp/gov-demo || return`, so it stops if the folder does not exist.

```bash
mkdir -p /tmp/gov-demo/src/main/java && cd /tmp/gov-demo || return
git init -q
echo '<project/>' > pom.xml && touch src/main/java/App.java
echo "Use tabs." > CLAUDE.md
ws detect                                        # → java
ai-governance install --scope project --agent claude --agent antigravity
```

- **Stack detection**: `ws detect` reads marker files (`pom.xml`, `package.json`,
  `pyproject.toml`, `Dockerfile`, …). Only the rules for detected stacks, plus the general ones,
  are installed.
- **Rules, written once**: each rule lives only in `.agents/rules/ai-governance-<id>.md`, with
  front matter every agent understands (`paths:` for Claude Code, `trigger`/`globs` for
  Antigravity; each ignores the other's keys). Claude Code reads them through symlinks in
  `.claude/rules/`; Codex reads the same folder. An agent loads a rule only when it touches a
  matching file; only the security rule is always on.
- **AGENTS.md**: one shared block between `<!-- ai-governance:start/end -->` markers. Any
  `CLAUDE.md` is moved into `AGENTS.md` and deleted, because Claude Code ignores `AGENTS.md`
  while a `CLAUDE.md` exists.
- **Gate**: `.claude/settings.json` gets a `Stop` hook that runs `ws check --changed --cache`
  when Claude ends a turn. On failure it blocks the turn once with a ≤1.5 KB summary.
  Set `gate = false` in the config to disable it.
- **Project state**: `.ai-governance/config.toml` (agents, extra/excluded rules, gate) and
  `.ai-governance/lock.json` (ownership ledger). Commit them together with the generated files.

**Check**:

```bash
cd /tmp/gov-demo || return
ls .agents/rules                                 # the rules (java + general ones)
ls -l .claude/rules | head -3                    # symlinks -> ../../.agents/rules/...
cat AGENTS.md                                    # starts with "Use tabs." then the block
cat .ai-governance/config.toml
ai-governance doctor                             # project:drift | OK | up to date
ai-governance budget                             # fixed bytes/tokens each agent loads per session
```

## 4. Keep rules in sync with the stack: `update`

```bash
cd /tmp/gov-demo || return
echo '[project]' > pyproject.toml && touch app.py
ai-governance update --dry-run                   # plans to add the Python rule
ai-governance update
ai-governance update --check && echo "up to date"   # exit 1 when something is stale (use in CI)
```

`update` re-detects stacks, adds rules that now apply, removes those that no longer do, and
refreshes content from the installed package version. A rule you edited by hand is kept and
reported. After upgrading the package, `ai-governance update --all` refreshes every
registered project.

## 5. Condensed output and Git hooks with `ws`

```bash
cd /tmp/gov-demo || return
ws run -- bash -c 'for i in $(seq 1 500); do echo "line $i"; done; echo "ERROR: boom"; exit 3'
echo "exit=$?"                                   # 3: the exit code is preserved
ws log --last --grep ERROR                        # or: ws log <id> with the id from the footer
```

`ws run` prints a summary (failures with context, tool summary line, tail) and saves the full
output privately (0600, kept 7 days / 200 logs).

```bash
cd /tmp/gov-demo || return
ws hooks install                                  # registers three config-based hooks in .git/config
git add -A && git commit -qm "chore(demo): init" && echo "commit OK"
git commit --allow-empty -m "anything" || echo "rejected by commit-msg"
ws check --changed --cache                       # the gate on demand; skipped if the tree is unchanged
                                                 # (the demo has a pom.xml: without Maven the test stage fails, which is expected)
```

| Hook | Event | Checks |
|---|---|---|
| `workspace-pre-commit` | pre-commit | `gitleaks protect --staged` (skipped without gitleaks) |
| `workspace-commit-msg` | commit-msg | Conventional Commits subject, ≤100 characters |
| `workspace-gate` | pre-push | Secrets, commit policies, linters, tests |

They are registered with `git config hook.<name>.*`, never `core.hooksPath`: Git runs them
first and the repository's own hooks (`.git/hooks`, Husky) afterwards. `ws hooks install
--global` registers them for every repository through `~/.gitconfig`.

## 6. Health checks

```bash
cd /tmp/gov-demo || return
ai-governance doctor
echo '{}' > .agents/settings.json && ai-governance doctor | grep gemini     # Antigravity no longer reads it
CLAUDE_CODE_USE_BEDROCK=1 ai-governance doctor | grep BEDROCK              # AGENTS.md unsupported there
rm .agents/settings.json
```

`doctor` also reports missing or locally edited files, a `CLAUDE*.md` that hides `AGENTS.md`,
the same hook installed at user and project scope (it would run twice), and drift.

## 7. Try it inside Claude Code

```bash
cd /tmp/gov-demo && claude
```

- Ask for a command with a large output (for example `ls -R /usr/lib`): the reply should show
  a summary with `ws log <id>` instead of thousands of lines.
- Ask it to use the scout to read `pom.xml`: the work runs on the cheaper model.
- Run `/context`: only the security rule and the global instructions are loaded until you
  open matching files.

## 8. Probe: verify what each agent really loads

Some behaviours are only documented, not proven on your machine (which instruction files an
agent reads, whether it follows symlinks, whether hooks fire, whether it delegates to a
subagent). The probe proves them with *canaries*: unique tokens such as `CANARY-AGENTS-MD`
placed in each candidate location. If the agent can quote a token, it loaded that location.

It runs in three moves, per agent:

1. **Build** a throwaway folder (nothing else is touched):

   ```bash
   ai-governance probe --agent claude     # prints "Probe project: <folder>" and a prompt
   ```

   The folder contains `AGENTS.md`, rules in every candidate place (for Claude, a rule reached
   through a symlink; for Antigravity, a rule with the combined front matter), a
   `probe-scout` subagent that starts every reply with `CANARY-SCOUT`, a `sample.probe` file
   that activates path-scoped rules, and (Codex/Antigravity) hooks that record which events
   fire.

2. **Ask the agent**: open it in that folder (`cd <folder> && claude`, `codex`, or Antigravity)
   and paste the printed prompt. It reads `sample.probe`, runs `echo probe`, asks
   `probe-scout` to read the file, and answers with the `CANARY-…` tokens it can see, e.g.
   `CANARY-AGENTS-MD, CANARY-CLAUDE-PATHS, CANARY-CLAUDE-LINK, CANARY-SCOUT`.

3. **Record the answer**:

   ```bash
   ai-governance probe --agent claude --verify --seen CANARY-AGENTS-MD,CANARY-CLAUDE-PATHS,CANARY-CLAUDE-LINK,CANARY-SCOUT
   ```

`--verify` prints what was proven (stored in `~/.local/state/ai-governance/probe/verified.json`):

| Field | Meaning | If it fails |
|---|---|---|
| `canaries_missing` | Locations the agent did not load | Report it: that location must change for this agent |
| `scout_verified` | The agent delegated to the subagent | The subagent file format needs adjusting |
| `shell_hooks_verified` | (Codex, Antigravity) Pre/PostToolUse fired with the shell command | Their output hooks stay uninstalled |
| `agent_frontmatter_hooks_fired` | (Antigravity) hooks declared in an agent's front matter fired | Fallback channel for the desktop app |

Then install the agent globally; Codex/Antigravity output hooks are added only if
`shell_hooks_verified` is true:

```bash
ai-governance install --scope user --agent codex        # after its probe
ai-governance install --scope user --agent antigravity  # after its probe (CLI and desktop app)
```

Expected tokens per agent:

| Agent | Tokens you should see |
|---|---|
| claude | `CANARY-AGENTS-MD`, `CANARY-CLAUDE-PATHS`, `CANARY-CLAUDE-LINK`, `CANARY-SCOUT` |
| codex | `CANARY-AGENTS-MD`, `CANARY-CODEX-NESTED`, `CANARY-SCOUT` |
| antigravity | `CANARY-AGENTS-MD`, `CANARY-AG-ALWAYS`, `CANARY-AG-GLOB`, `CANARY-AG-DUAL`, `CANARY-SCOUT` |

## 9. Uninstall

```bash
cd /tmp/gov-demo || return
ai-governance uninstall --agent claude --agent antigravity
ai-governance uninstall --scope user --agent claude --agent codex --agent antigravity
ws hooks uninstall
```

Uninstall removes exactly what the ledger recorded: marker blocks are cut out, merged hook
entries removed, owned files deleted (unless you edited them), and files that ai-governance
created and that end up empty are deleted.
