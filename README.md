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

### Full Monorepo Editable Installation

Clone the repository and install all packages alongside developer dependencies:

```bash
# 1. Create and activate a virtual environment
uv venv
source .venv/bin/activate

# 2. Install the complete monorepo in editable mode with dev dependencies
uv pip install -e ".[dev]"
```

Once installed, you will have **9 global executable CLI commands** registered on your PATH:

| Command | Source Package | Description |
|---|---|---|
| `spec` | `packages/spec` | Governance & Spec-Driven Development CLI |
| `ws` | `packages/workspace` | Workspace, microservices & DevOps manager |
| `governance`| `packages/ai-governance` | Master AI governance CLI |
| `rules` | `packages/ai-governance` | 28 software engineering standards catalog & injector |
| `frugal` | `packages/ai-governance` | Output condenser & context frugality trimmer |
| `statusline`| `packages/ai-governance` | Real-time ANSI token cost & context telemetry bar |
| `progreso` | `packages/ai-governance` | Cross-session task tracking (~300 tokens) |
| `jira` | `packages/ai-governance` | Jira ticket querying and status transitions in Markdown |
| `confluence`| `packages/ai-governance` | Confluence search and page reader in Markdown |

---

## 🔄 Integrated Daily Workflow

How the 3 tools collaborate in a typical developer feature cycle:

```bash
# 1. Workspace: Create an isolated environment for the new feature
ws worktree /path/to/base-repo /path/to/worktree feature/order-checkout

# 2. AI-Governance: Register the task and inject standards into agent config
progreso nueva ONB-2050 --titulo "Order checkout refactor"
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




