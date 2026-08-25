# Cucco SpecOps Engine — Multi-Agent AI Governance & Deterministic Workspace Monorepo

**Cucco SpecOps Engine** is a high-precision, decoupled monorepo built according to **Clean Architecture**, **SOLID**, **Domain-Driven Design (DDD)**, **DRY**, and **YAGNI** principles. It combines a deterministic, zero-hallucination workspace manager (`ws`) with an autonomous AI governance harness (`sdd`), a native FastMCP server, and a modular engineering rules catalog.

```
cucco-specops-engine/
├── rules/                  # Modular Engineering Rules Catalog (Global & Scoped)
│   ├── global/             # Non-negotiable universal rules (anti-looping, commits, security, SDD)
│   └── scoped/             # Stack-specific standards (Java, Python, TypeScript, React, Go, Rust, DevOps)
├── packages/
│   ├── common/             # Subproject 0: Shared base, typing, safe subprocess & project parsers (cucco-common)
│   │   ├── src/devscripts_common/
│   │   └── tests/
│   ├── workspace/          # Subproject 1: Deterministic Workspace Engine & CLI `ws` (cucco-workspace)
│   │   ├── src/workspace_engine/
│   │   └── tests/
│   └── sdd/                # Subproject 2: Full AI Governance Engine & CLI `sdd` (cucco-sdd)
│       ├── src/sdd_engine/
│       ├── skills/         # 14 Canonical SDD Agent Skills
│       ├── templates/      # Formal specification templates
│       └── tests/
├── docs/                   # Cross-cutting architectural documentation
├── install.py              # Interactive multi-agent installer & package setup
├── uninstall.py            # Deterministic uninstaller & agent cleaner
├── pyproject.toml          # Monorepo build orchestrator
└── README.md               # Master documentation
```

---

## ⚡ 1. Complete Step-by-Step Installation Guide

### Prerequisites
- **Python**: `>= 3.10` (Python 3.11 or 3.12 recommended).
- **Git**: `>= 2.30` (with worktree support).
- **Package Manager**: [`uv`](https://github.com/astral-sh/uv) (recommended for millisecond installs) or standard `pip`.

---

### Step 1: Clone the Repository
```bash
git clone https://github.com/Ezuser/cucco-specops-engine.git
cd cucco-specops-engine
```

### Step 2: Create & Activate Virtual Environment
```bash
# Using uv (fastest):
uv venv .venv
source .venv/bin/activate

# Or using standard python:
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Run the Interactive Multi-Agent Installer
```bash
python3 install.py
```
The installer will:
1. Display an interactive terminal checkbox menu to select your active AI coding assistants (Claude Code, Cursor IDE, Google Antigravity, Windsurf, Copilot, etc.).
2. Automatically deploy the modular rules catalog into the selected agent directories.
3. Install `cucco-common`, `cucco-workspace`, and `cucco-sdd` in editable mode (`-e`), making the CLI binaries `ws` and `sdd` immediately available in your PATH.

### Step 4: Verify the Installation
```bash
ws doctor
sdd --help
```

### Step 5: (Optional) Install the Pre-Push Quality Gate Globally
Protect all repositories on your system with automated secret scanning, linting, and zero-AI-mention policy enforcement before any `git push`:
```bash
ws hooks install --global
```

---

## 🚀 2. Simple & Practical Usage Examples

### 🛠️ Workspace Engine Examples (`ws`)

#### 1. Diagnose Your Development Environment
```bash
ws doctor
```
*Scans your system and reports the availability of Git, uv, JDK, Maven, Gradle, Node.js, npm, Docker, and Kubernetes.*

#### 2. Create an Atomic Git Worktree
```bash
ws worktree feature/user-auth
```
*Creates an isolated Git worktree in `../workspace-feature-user-auth` for branch development without dirtying your main tree.*

#### 3. Compile & Install Multi-Stack Dependencies
```bash
ws build
ws deps
```
*Automatically detects whether the project is Maven, Gradle, npm, Go, or Python and runs the correct build command.*

#### 4. Launch Local Microservices with Interactive TUI
```bash
ws run-local
```
*Discovers local services, allocates dedicated ports (8000–8999), rewrites URLs, and opens a live log streaming TUI.*

---

### 🤖 SDD & AI Governance Engine Examples (`sdd`)

#### 1. Initialize SDD in Any Repository
```bash
cd /path/to/my-project
sdd init
```
*Auto-detects the repository technology stack, generates the technical constitution (`.specify/constitution/constitution.md`), and configures Multi-AI adapters.*

#### 2. Run the 8-Phase Spec-Driven Development Workflow
```bash
# Phase 1: Functional Specification (spec.md)
sdd specify "User Authentication with JWT"

# Phase 2: Ambiguity & Risk Audit (clarify.md)
sdd clarify

# Phase 3: Technical Blueprint & Zod/DTO Contracts (plan.md)
sdd plan

# Phase 4: Quality Gates & Definition of Done (checklist.md)
sdd checklist

# Phase 5: Atomic Task Breakdown (tasks.md)
sdd tasks

# Phase 6: Static Cross-Artifact & AST Audit
sdd analyze

# Phase 7: Multi-Agent Execution (Worker + QA Reviewer)
sdd harness run

# Phase 8: Final Acceptance & Pull Request Creation
sdd converge
sdd finish
```

#### 3. Save 40%–75% Tokens with Dynamic Rule Matching
```bash
sdd match-rules --files src/controllers/user.ts src/models/user.ts
```
*Analyzes the target files and renders only the relevant global and scoped rules for inclusion in the AI context window.*

#### 4. Fast-Path Hotfix Workflow (`sdd quick`)
```bash
sdd quick "Fix null pointer in payment webhook handler"
```
*Creates an atomic micro-spec, executes the fix, and runs verification in a single focused step.*

#### 5. Launch FastMCP Server for Claude Code / Cursor
```bash
sdd mcp
```
*Starts the JSON-RPC 2.0 stdio Model Context Protocol server exposing `sdd_verify`, `ws_clean`, and SDD resources to external AI clients.*

---

## 📋 3. CLI Command Reference Tables

### `ws` — Workspace Engine Commands
| Command | Description |
|---|---|
| `ws doctor` | Diagnoses installed compilers, runtimes, and system tools |
| `ws hooks` | Git Hooks manager (`install`, `status`, `uninstall`) |
| `ws generate` | Generates a new multi-repo worktree workspace |
| `ws edit` | Adds/removes repositories in active workspace |
| `ws worktree` | Creates an atomic worktree for a branch |
| `ws clean` | Deep cleans caches and build artifacts |
| `ws stop` | Stops background services in the workspace |
| `ws reset` | Resets repositories to upstream clean state |
| `ws delete` | Deletes workspace and cleans worktrees |
| `ws build` | Multi-stack build (Maven, Gradle, npm, Go, Python) |
| `ws deps` | Installs dependencies across workspace repos |
| `ws java` | Configures matching JDK version via SDKMAN |
| `ws env-init` | Interactively initializes `.env` files from templates |
| `ws env-load` | Loads and inspects environment variables |
| `ws benchmark`| Runs parallel test suite benchmark with metrics |
| `ws run-local`| Orchestrates local microservices with live TUI |
| `ws kube` | Interactive Kubernetes pod inspector and log streamer |

### `sdd` — SDD AI Governance Commands
| Command | Description |
|---|---|
| `sdd init` | Initializes SDD workspace and generates AI adapters |
| `sdd feature <name>` | Sets or inspects active feature with worktree isolation |
| `sdd specify` / `sdd plan` | Assists in authoring lifecycle phase specifications |
| `sdd analyze` | Statically audits cross-artifact consistency and AST contracts |
| `sdd verify` | Runs automated quality gate (linters, tests, secrets) |
| `sdd harness run` | Multi-agent execution orchestrator (Worker + QA) |
| `sdd match-rules` | Dynamically filters rules by active files to save tokens |
| `sdd mcp` | Launches FastMCP JSON-RPC 2.0 stdio server |
| `sdd quick <desc>` | Fast-path atomic workflow for bug fixes and patches |
| `sdd audit [--deep]` | Comprehensive codebase debt audit in `.specify/tech-debt.md` |
| `sdd gate` | Quality gate baseline capture and regression verification |
| `sdd hook` | Pre-tool and post-tool security/verification hooks |
| `sdd finish` | Finalizes feature cycle, creates PR, and cleans worktree |
| `sdd sync` | Reinstalls CLI and synchronizes project AI adapters |
| `sdd revoke` | Revokes SDD setup with automated safety backup |

---

## 🧪 4. Running Tests

Execute the complete deterministic test suite:

```bash
uv run pytest
```

---

## 📚 5. Documentation Hub

For in-depth guides, visit the [`docs/`](docs/README.md) directory:
- [**Monorepo Architecture**](docs/architecture/monorepo.md)
- [**Git Hooks & Quality Gate Guide**](docs/workspace/git-hooks.md)
- [**SDD Lifecycle Step-by-Step**](docs/sdd/lifecycle.md)
- [**SDD Multi-Agent Architecture**](docs/sdd/architecture.md)
- [**SDD Skills Catalog & Agent Matrix**](docs/sdd/skills-reference.md)
- [**Modular Rules Catalog**](rules/README.md)
