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
- **Telemetry & Budget Pacing**: High-visibility real-time ANSI statusline and business-day budget pacing (`ritmo`).
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
- `statusline`: Real-time ANSI telemetry statusline.
- `telemetry`: Local usage estimates, price-cache maintenance, calibration, and thresholds.
- `progreso`: Lightweight cross-session task tracking.
- `jira`: Fast, lightweight Jira CLI client in Markdown.
- `confluence`: Fast, lightweight Confluence CLI client in Markdown.

### 3. Environment Variables (Optional)
To enable Jira and Confluence tools, configure in your environment (`~/.zshrc` or `.env`):
```bash
export JIRA_URL="https://company.atlassian.net"
export JIRA_EMAIL="your-user@company.com"
export JIRA_API_TOKEN="your-api-token"

export CONFLUENCE_URL="https://company.atlassian.net/wiki"
export CONFLUENCE_EMAIL="your-user@company.com"
export CONFLUENCE_API_TOKEN="your-api-token"
```

---

## 🏛️ Internal Architecture

The package is organized around 6 decoupled pillars:

```
packages/ai-governance/
├── catalog/                   # 28 canonical rules in Markdown (SSOT)
│   ├── 1-core/                # SOLID, DDD, Clean Architecture, Testing, Security...
│   ├── 2-stacks/              # Python, TypeScript, React, Java, Go, Rust, Kotlin...
│   ├── 3-infrastructure/      # K8s, Docker, Migrations, CI/CD, Observability...
│   └── 4-docs/                # Architecture diagrams & technical docs
├── src/ai_governance/
│   ├── cli.py                 # Master unified CLI dispatcher (`governance`)
│   ├── rules/                 # Standards catalog engine and injector (`rules`)
│   │   ├── agents.py          # Universal AGENTS.md rules injector & manager
│   │   └── core/              # Catalog, injector, storage, and TUI components
│   ├── frugality/             # Test trimmers and context guards (`frugal`)
│   ├── telemetry/             # ANSI statusline, cost monitor, and `ritmo` algorithm
│   ├── session/               # Cross-session progress tracker (`progreso`)
│   └── tools/                 # Native Markdown CLI tools (`jira`, `confluence`)
└── tests/                     # Unit and integration test suites
```

### Component Data Flow
1. **Standards & Agents**: `rules` reads Markdown definitions from `catalog/` and injects delimited sections with safe markers (`<!-- rules:start -->`) directly into `AGENTS.md`. Uninstalling cleanly removes only the injected block without touching user configurations.
2. **Context Frugality Engine**: Intercepts Bash command outputs via stdin/stdout (`--post-bash`). It detects test runners, elides green passed lines, and surfaces exclusively failure blocks (`FAILURES`), broken assertions, and the summary line.
3. **Session Persistence**: Stores the active state in `~/.specops/progreso/<id>.json` (compact) and extended logs in `<id>.md`. Enables any agent to resolve the active task from the current git repository and branch via `progreso aqui`.

---

## 📖 Command Reference & Practical Guide

### 1. Master CLI (`governance`)
Unified entrypoint for all subsystems:
```bash
governance rules        # Launch rules manager
governance frugal       # Launch context frugality engine
governance statusline   # Display telemetry statusline
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

### 4. Telemetry & Budget Pacing (`statusline` & `ritmo`)

```bash
# Real-time ANSI statusline (session cost, context window %, 5h rate limits)
statusline

# Business-Day Budget Pacing (algorithm factoring business days in month)
ritmo --budget 150 --spent 42.50
# Visualizes whether your burn rate is ahead or behind budget target.

# Scan Claude Code transcripts for consumption breakdown
governance usage --budget 150

# Detailed machine-readable estimate with cache tiers and server tools
telemetry report --json

# Explicit maintenance operations (the statusline never uses the network)
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

Portable Claude command prompts are packaged under
`ai_governance/resources/claude/commands/`. They are optional resources and do not modify
global Claude configuration automatically.

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
