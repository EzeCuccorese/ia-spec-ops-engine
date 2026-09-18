# SpecOps AI Governance

**SpecOps AI Governance** is the core engine for context frugality, software engineering standards, token cost telemetry, and cross-session state preservation for AI coding agents.

---

## 🎯 Purpose & Overview

Continuous development with AI coding agents (Claude Code, Antigravity, Cursor, Windsurf, Codex) commonly suffers from two critical bottlenecks:
1. **Context Bloat & Token Waste**: Test suites emitting hundreds of lines of passing assertions, massive JSON payloads, and verbose directory listings degrade the agent's attention window and inflate token costs.
2. **Loss of Technical Invariants**: AI code generation frequently drifts away from SOLID, DDD, Clean Architecture, immutability, or creates bloated God classes.

`ai-governance` solves this via:
- **Canonical 28-Rule Catalog**: Reversibly injectable into any AI coding agent configuration.
- **Active Context Frugality**: Intelligent output condensation for test runners (`pytest`, `jest`, `vitest`, `go test`, `cargo test`) that hides passing test spam while preserving failure traces.
- **Telemetry & Budget Pacing**: Local usage estimates and business-day budget pacing (`ritmo`).
- **Ultralight Cross-Session State (`progreso` / `progress`)**: Compact JSON state (~300 tokens) to effortlessly pause, clear, and resume multi-repo tasks without hauling dead conversational context.
- **Zero-Overhead CLI Tools (`jira`, `confluence`)**: Native CLI tools outputting clean Markdown without MCP token tax.

---

## 💻 Installation & Setup

### 1. Editable Installation
From the monorepo root or package directory:

```bash
# Individual package installation with uv
uv pip install -e packages/ai-governance

# Or with standard pip
pip install -e packages/ai-governance
```

### 2. Global Executable CLI Commands
Installation registers these commands on your PATH:
- `governance`: Unified master CLI orchestrator.
- `rules`: Engineering standards catalog and reversible multi-agent injector.
- `frugal`: Context condenser and runtime trimmer.
- `telemetry`: Local usage estimates, price-cache maintenance, calibration, and thresholds.
- `progreso`: Lightweight cross-session task tracking.
- `jira`: Fast, lightweight Jira CLI client in Markdown.
- `confluence`: Fast, lightweight Confluence CLI client in Markdown.

### 3. Environment Variables (Optional)
To enable Jira and Confluence tools, configure in your environment (`~/.zshrc` or `.env`):
```bash
export ATLASSIAN_URL="https://company.atlassian.net"
export ATLASSIAN_EMAIL="your-user@company.com"
export ATLASSIAN_API_TOKEN="your-api-token"
# Optional timeout in seconds (default: 30.0)
# export ATLASSIAN_TIMEOUT=30.0
```

---

## 🏛️ Internal Architecture

The package is organized around 6 decoupled pillars:

```
packages/ai-governance/
├── src/ai_governance/
│   ├── catalog/               # Packaged canonical rules (28 Markdown files)
│   ├── resources/workflows/   # Agent-neutral progress protocol
│   ├── cli.py                 # Master unified CLI dispatcher (`governance`)
│   ├── rules/                 # Standards catalog engine and injector (`rules`)
│   │   ├── agents.py          # Universal AGENTS.md rules injector & manager
│   │   └── core/              # Catalog, injector, storage, and TUI components
│   ├── frugality/             # Test trimmers and context guards (`frugal`)
│   ├── telemetry/             # Cost monitor and `ritmo` algorithm
│   ├── session/               # Cross-session progress tracker (`progreso`)
│   └── tools/                 # Native Markdown CLI tools (`jira`, `confluence`)
└── tests/                     # Unit and integration test suites
```

### Component Data Flow
1. **Standards & Agents**: `rules` reads Markdown definitions from `catalog/` and injects delimited sections with safe markers (`<!-- rules:start -->`) directly into `AGENTS.md`. Uninstalling cleanly removes only the injected block without touching user configurations.
2. **Context Frugality Engine**: Intercepts Bash command outputs via stdin/stdout (`--post-bash`). It detects test runners, elides green passed lines, and surfaces exclusively failure blocks (`FAILURES`), broken assertions, and the summary line.
3. **Session Persistence**: Stores compact task state in `~/.specops/progress/tasks/<id>.json` and extended logs in `~/.specops/progress/tasks/<id>.md`. Enables any agent to resolve the active task from the current git repository and branch via `progreso aqui`.

---

## 📖 Command Reference & Practical Guide

### 1. Master CLI (`governance`)
Unified entrypoint for all subsystems:
```bash
governance rules        # Launch rules manager
governance frugal       # Launch context frugality engine
governance ritmo        # Calculate monthly budget pacing
governance usage        # Scan local Claude Code transcripts
governance task         # Manage cross-session tasks
```

---

### 2. Software Engineering Standards (`rules`)
Manages the 28 canonical rules and reversibly injects them into configured AI agents via `AGENTS.md`.

```bash
# List all 28 canonical rules with their triggers
rules list

# Launch the interactive TUI menu
rules

# Non-interactive installation (Global or Project-Local)
rules install --global --all   # Install all rules into ~/.specops/rules/
rules install --local --all    # Install all rules into active project (.specops/rules/)

# Clean, reversible uninstallation
rules uninstall --global
rules uninstall --local
```

**Universal Agent Standard**: All AI coding agents (Antigravity, Claude Code, Cursor, Windsurf, Aider, etc.) follow the universal open standard `AGENTS.md`.

---

### 3. Context Frugality Engine (`frugal`)
Minimizes token consumption by condensing noisy command outputs. Designed for agent hook integration or direct terminal pipelines.

```bash
# Process Bash command output via agent hook (fail-open)
frugal --post-bash < console_output.json

# Directly condense test output (hides green spam, preserves stack traces)
pytest | frugal --trim-test

# Check active version and thresholds
frugal --version
```

> **Bypass**: To disable trimming for a specific execution, append `#nofrugal` to the command line or export `FRUGAL=0`.

---

### 4. Telemetry & Budget Pacing (`ritmo`)

```bash
# Business-Day Budget Pacing (algorithm factoring business days in month)
ritmo --budget 150 --spent 42.50
# Visualizes whether your burn rate is ahead or behind budget target.

# Scan Claude Code transcripts for consumption breakdown
governance usage --budget 150

# Detailed machine-readable estimate with cache tiers and server tools
telemetry report --json

# Explicit maintenance operations (telemetry never uses the network by itself)
telemetry prices update
telemetry calibrate --from 2026-09-01 --to 2026-09-07 --actual 42.50
telemetry thresholds --notify
```

Telemetry reads local Claude transcripts, so every cost is an estimate. Provider billing
remains authoritative. Configuration is stored under `~/.specops/usage-monitor/config.json`;
`holiday_dates` accepts explicit ISO dates for a local business-day calendar. Price refresh
is manual and validates the remote schema before atomically replacing the local cache.

---

### 5. Cross-Session Progress Tracking (`progreso` / `progress`)
Preserves engineering context across sessions. Stores compact metadata indexed by Jira key or freeform slug.

```bash
# List all currently active tasks
progreso list

# Resolve active task automatically from current branch or repo
progreso aqui

# Create a new task
progreso nueva ONB-1164 --titulo "Payment architecture migration"

# View compact state summary (~300 tokens)
progreso ver ONB-1164

# View full narrative markdown log
progreso ver ONB-1164 --full

# Close a completed task (state remains reopenable)
progreso cerrar ONB-1164

# Explicit lifecycle and structured compact state
progress pause ONB-1164 --reason "Waiting for review"
progress resume ONB-1164
progress reopen ONB-1164
progress step ONB-1164 add "Run native acceptance"
progress step ONB-1164 done 1
progress fact ONB-1164 "Remote CI passed at SHA abc123"
progress repo ONB-1164 add . --branch feature/onb-1164 --pr 42
progress reference ONB-1164 jira ONB-1164
progress link ONB-1164 "PR" https://example.test/pr/42
progress note ONB-1164 "Decision and rationale"
progress digest --id ONB-1164
progress list --all --json
```

`progress here` resolves a Jira-like key from the branch first, then falls back to an
unambiguous registered repository. Compact arrays are bounded; older entries move to the
long log instead of growing the default task payload indefinitely. A one-time
`progress migrate-legacy <directory>` command imports the former `progress-to-md` layout.

A portable neutral progress workflow is packaged under
`ai_governance/resources/workflows/progress.md`. It provides standard, agent-agnostic
patterns for saving, resuming, and completing tasks across sessions.

---

### 6. Zero-Overhead CLI Tools (`jira` & `confluence`)
Query enterprise systems directly formatted in Markdown without heavy MCP token overhead.

```bash
# View Jira ticket in clean Markdown
jira issue ONB-1164

# Transition Jira ticket status
jira transition ONB-1164 "In Progress"

# Fetch Confluence page converted to Markdown
confluence get 84920492

# Search Confluence pages
confluence search "Authentication Architecture"
```

---

### 7. Agent Output Mode

All `ai-governance` CLIs share one output layer (`ai_governance/output.py`). When a
command runs under an AI coding agent, output is compact and deterministic instead
of the rich, human-oriented rendering used in an interactive terminal.

- **Detection**: agent mode is ON whenever stdout is not a TTY, or when
  `SPECOPS_AGENT=1` is set. `SPECOPS_AGENT=0` forces it off (useful for tests or a
  human piping output). Detection is re-evaluated on every call — nothing is cached.
- **Budget**: agent-mode output is truncated to roughly 20 lines / 1500 characters,
  ending in a `more: <hint>` line when something was cut.
- **Escaping the budget**: pass `--full` on commands that support it to disable
  truncation, or `--json` to get a single dense JSON line instead of a table.
- Status lines use plain `OK:` / `WARN:` / `ERROR:` / `INFO:` prefixes; `ERROR:`
  lines go to stderr, everything else to stdout.

---

### 8. Harness Tools & Self-Wiring (`governance harness`)

The rules catalog (`packages/ai-governance/src/ai_governance/catalog/manifest.json`)
also declares a small set of **deterministic tools** — `frugal`,
`telemetry`, `progress`, `jira`, `confluence`, and the `ws` tools from
`packages/workspace` — each with a trigger (`before-shell-command`,
`after-shell-command`, `on-turn-end`, `on-worktree-create`, or
`on-demand`).

```bash
# List the deterministic tools catalog
governance harness list
governance harness list --json

# Print the rendered self-wiring block without writing anything
governance harness show

# Inject the wiring block into AGENTS.md (idempotent, reversible)
governance harness install --local --root .
governance harness install --global

# Remove it again
governance harness uninstall --local --root .
```

**No installer, by design.** `governance harness install` never writes
`~/.claude/settings.json` or any other host configuration file. It only injects a
`<!-- harness:start --> ... <!-- harness:end -->` block into `AGENTS.md` (the same
target the `rules` adapter uses) documenting, for every automatic-trigger tool,
where that trigger lives on a known host (see `rules/core/hosts.py`) and what to do
when the runtime does not support that hook at all: run the command manually at
that point in the workflow. The agent reading `AGENTS.md` self-configures its own
runtime from that documentation; `governance doctor` only reads and reports, it
never writes host config either.

Any on-demand deterministic tool should be announced with one line before use:
`⚙ <tool-id> <args>` (see rule `00-deterministic-first`).

---

### 9. Doctor (`governance doctor`)

A read-only, deterministic health check — it writes nothing.

```bash
governance doctor
governance doctor --global
governance doctor --json
governance doctor --host claude-code
```

It reports one line per check (`STATUS  name — hint`) plus a
`summary: N ok, M missing, K warn` line, and checks:

1. **Tool presence**: each deterministic tool's command is on `PATH`
   (`shutil.which`); hint is the `uv pip install -e packages/<pkg>` to run.
2. **Host wiring**: for the detected (or `--host`-forced) host, whether each
   automatic tool's trigger is actually wired in that host's config (e.g.
   `~/.claude/settings.json` hooks for `claude-code`). `N/A` when no
   supported host is detected.
3. **`AGENTS.md` blocks**: whether the `rules:start` and `harness:start` blocks are
   present at the resolved target (local or `--global`).
4. **Runtime dir**: whether `SPECOPS_USAGE_DIR` (or `~/.specops/usage-monitor`)
   exists and is writable.

**Exit codes**: `0` when everything checked is `OK` or `WARN`/`N/A`, `1` when any
check is `MISSING`, `2` on an unexpected internal error.
