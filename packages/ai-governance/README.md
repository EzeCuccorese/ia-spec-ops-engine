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
Installation immediately registers 7 commands on your PATH:
- `governance`: Unified master CLI orchestrator.
- `rules`: Engineering standards catalog and reversible multi-agent injector.
- `frugal`: Context condenser and runtime trimmer.
- `statusline`: Real-time ANSI telemetry statusline.
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
│   ├── adapters/              # Agent adapters (Claude, Codex, Cursor, Windsurf)
│   ├── frugality/             # Test trimmers and context guards (`frugal`)
│   ├── telemetry/             # ANSI statusline, cost monitor, and `ritmo` algorithm
│   ├── session/               # Cross-session progress tracker (`progreso`)
│   └── tools/                 # Native Markdown CLI tools (`jira`, `confluence`)
└── tests/                     # Unit and integration test suites
```

### Component Data Flow
1. **Standards & Adapters**: `rules` reads Markdown definitions from `catalog/` and utilizes `adapters/` to inject delimited sections with safe markers (`<!-- managed by specops: start -->`). Uninstalling cleanly cleans only the injected block without touching user configurations.
2. **Context Frugality Engine**: Intercepts Bash command outputs via stdin/stdout (`--post-bash`). It detects test runners, elides green passed lines, and surfaces exclusively failure blocks (`FAILURES`), broken assertions, and the summary line.
3. **Session Persistence**: Stores the active state in `~/.claude/progreso/<id>.json` (compact) and extended logs in `<id>.md`. Enables any agent to resolve the active task from the current git repository and branch via `progreso aqui`.

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
Manages the 28 canonical rules and reversibly injects them into configured AI agents.

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

**Supported AI Coding Agents**: Claude Code (`CLAUDE.md`), OpenAI Codex (`AGENTS.md`), Cursor (`.cursorrules`), Windsurf (`.windsurfrules`).

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
```

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

# Update steps and linked repositories
progreso paso ONB-1164 "Write unit tests for PaymentGateway" --done
progreso repo ONB-1164 "/path/to/payment-service" --branch "feature/gateway"

# Archive and close a completed task
progreso cerrar ONB-1164
```

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

