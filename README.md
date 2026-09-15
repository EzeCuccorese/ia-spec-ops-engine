# SpecOps Engine

**SpecOps Engine** is a decoupled monorepo providing comprehensive infrastructure for AI-assisted software engineering and local developer workspace orchestration:

```
                                  SPECOPS ENGINE
 ┌───────────────────────────┬───────────────────────────┬───────────────────────────┐
 │     AI-GOVERNANCE         │           SPEC            │         WORKSPACE         │
 ├───────────────────────────┼───────────────────────────┼───────────────────────────┤
 │ • 28 Engineering Rules    │ • Honest SDD Lifecycle    │ • Multi-Repo Workspaces   │
 │ • Context Frugality       │ • Preflight & Worktrees   │ • Git Worktree Isolation  │
 │ • Telemetry & Ritmo Pacing│ • Test Traceability (@s)  │ • Local Microservices     │
 │ • Sessions (progreso)     │ • Immutable Evidence      │ • Pre-Push Quality Gate   │
 │ • Jira & Confluence Tools │ • AST Mutation Testing    │ • K8s, JDK & Build Tools  │
 └───────────────────────────┴───────────────────────────┴───────────────────────────┘
```

---

## 📦 Monorepo Packages

Each package is strictly modular, independent, and comes with its own hermetic test suite:

1. [**`packages/ai-governance`**](packages/ai-governance/README.md):
   Software engineering standards catalog (28 canonical rules across Core, Stacks, Infra, Docs), context frugality runtime for condensing test outputs, high-visibility ANSI `statusline`, business-day budget pacing algorithm (`ritmo`), lightweight cross-session task tracking (`progreso`), and zero-MCP-overhead Markdown tools (`jira`, `confluence`).
2. [**`packages/spec`**](packages/spec/README.md):
   Deterministic governance and Spec-Driven Development (SDD) engine for AI coding agents. Enforces the honest loop: `init -> agent install -> preflight -> new -> plan -> tasks -> work -> verify -> finish` with strict JSON `argv` verification without shell evaluation and immutable evidence recording.
3. [**`packages/workspace`**](packages/workspace/README.md):
   Local development orchestrator: deterministic multi-repo workspace management using Git worktrees (`ws generate`, `ws worktree`), local microservices orchestration with auto-discovery and interactive TUI (`ws run-local`), 5-stage pre-push Quality Gate (`ws hooks`), and Kubernetes pod environment utilities (`ws kube`).

---

## 💻 Quick Installation & Setup

### Prerequisites
- **Python >= 3.11**
- [**uv**](https://github.com/astral-sh/uv) (Extremely fast Python package manager)
- **Git**

### Post-Clone Quickstart (For Humans & AI Agents)

Clone the repository and run the 4-step bootstrap:

```bash
# 1. Create virtualenv and install all packages in editable mode
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 2. Initialize project configuration (.specops/config.json)
specops config init --local --yes
# Or directly via repo binary: ./bin/specops config init --local --yes

# 3. Configure your AI agent governance adapter (antigravity, claude, cursor, windsurf, aider, custom, all)
specops agent install <your-agent>
# Example: specops agent install antigravity

# 4. Run full health diagnostics and spec audit
specops doctor && specops audit
```

> 📖 **Full AI Agent Guide**: See [docs/AGENTS_GUIDE.md](docs/AGENTS_GUIDE.md) for complete details on autonomous agent operation, SDD lifecycle, and tool references.

---

## 🛠️ CLI Commands & Tool Ecosystem

The monorepo registers executable CLI commands on your PATH (and also provides standalone wrapper scripts under `./bin/`):

| Command | Binary Path | Source Package | Description |
|---|---|---|---|
| **`specops`** | `./bin/specops` | Monorepo Master | Master orchestration CLI (`config`, `agent`, `doctor`, `audit`, `rules`, etc.) |
| **`spec`** | `./bin/spec` | `packages/spec` | Governance & Spec-Driven Development (SDD) CLI |
| **`ws`** | `./bin/ws` | `packages/workspace` | Workspace, Git worktrees & local microservices manager |
| **`governance`**| `./bin/specops` | `packages/ai-governance` | AI governance, telemetry & rules CLI |
| **`rules`** | — | `packages/ai-governance` | 28 software engineering standards catalog & injector |
| **`frugal`** | — | `packages/ai-governance` | Output condenser & context frugality trimmer |
| **`statusline`**| — | `packages/ai-governance` | Real-time ANSI token cost & context telemetry bar |
| **`progreso`** | — | `packages/ai-governance` | Cross-session task tracking (~300 tokens) |
| **`jira`** | — | `packages/ai-governance` | Jira ticket querying and status transitions in Markdown |
| **`confluence`**| — | `packages/ai-governance` | Confluence search and page reader in Markdown |
| **`telemetry`**| — | `packages/ai-governance` | Local Claude usage estimates, prices, thresholds and calibration |

---

## 🔄 Integrated Daily Workflow

How the 3 tools collaborate in a typical developer feature cycle:

```bash
# 1. Workspace: Create an isolated environment for the new feature
ws worktree /path/to/base-repo /path/to/worktree feature/order-checkout

# 2. AI-Governance: Register the task and inject standards into agent config
progreso nueva ONB-2050 --titulo "Order checkout refactor"
progress step ONB-2050 add "Run acceptance tests"
progress fact ONB-2050 "Baseline verified"
rules install --local --all

# 3. Spec: Validate baseline and initialize the formal specification
spec preflight "order-checkout" --worktree
spec new "order-checkout" --description "Idempotent payment processing"
spec plan
spec tasks

# 4. Test-Driven Development (TDD):
spec work
spec test-assist --next

# 5. Deterministic verification and sign-off:
spec verify
spec finish

# 6. Quality Gate: Ensure zero secrets and clean code before pushing
ws hooks run
git push origin feature/order-checkout
```

---

## 🧪 Unified Testing

Run all hermetic test suites across all packages:

```bash
pytest
```



