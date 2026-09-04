# cucco-workspace — Deterministic Workspace & Microservices Engine

**Workspace Engine (`ws`)** is the deterministic orchestrator for local development environments, multi-repository Git worktree isolation, multi-stack builds and dependency management, local/global pre-push Quality Gates, and microservices runtime supervision with an interactive TUI.

---

## 🎯 Purpose & Overview

Developing modern distributed systems and microservices architectures poses recurring challenges:
- Managing multiple interconnected repositories concurrently without polluting branches or duplicating entire workspace directories.
- Spinning up 5 to 10 microservices locally while manually resolving port collisions and inter-service endpoints.
- Leaking secrets, syntax errors, or AI markers into upstream branches, causing CI failures.
- Inconsistent JDK, Node, or environment variable versions across development machines.

`ws` automates and unifies these workflows under a single, deterministic CLI interface.

---

## 💻 Installation & Setup

### 1. Editable Installation
From the monorepo root:

```bash
# With uv (recommended)
uv pip install -e packages/workspace

# Or with standard pip
pip install -e packages/workspace
```

### 2. Global Executable CLI Commands
Installation registers the global command:
- `ws`: Master CLI for workspaces, local microservices, and DevOps utilities.

### 3. Environment Diagnostics (`ws doctor`)
Instantly inspect system compilers, tools, and runtimes:
```bash
ws doctor
```
Verifies availability of: Git, uv, kubectl, Java JDK, Maven, Node.js, npm, Docker, and the active status of Git Quality Gate hooks.

---

## 🏛️ Internal Architecture

The engine is modularly structured across 4 subsystems:

```
packages/workspace/
├── src/workspace_engine/
│   ├── cli/                   # 16 subcommands unified by main.py
│   │   ├── main.py            # Master CLI dispatcher (`ws`)
│   │   ├── manage_hooks.py    # Subcommand `ws hooks`
│   │   ├── generate_workspace.py # Interactive multi-repo workspace generator
│   │   ├── create_worktree.py # Atomic Git worktree generator
│   │   ├── kube_env.py        # Subcommand `ws kube`
│   │   └── ...
│   ├── run_local/             # Local microservices orchestrator
│   │   ├── discovery.py       # Service auto-discovery and deterministic ports (8000-8999)
│   │   ├── service_wiring.py  # Dynamic URL re-writing (wire_urls)
│   │   ├── process_manager.py # Non-blocking background supervisor and log streaming
│   │   ├── profiles.py        # JSON execution profile management
│   │   └── tui.py             # Interactive dashboard with live logs and Swagger links
│   ├── services/              # Domain services and quality gates
│   │   ├── git_hooks.py       # 5-stage Quality Gate (Secrets, Commits, Linters, Tests)
│   │   ├── configure_repos.py # Repository synchronization and worktree binding
│   │   └── benchmark_display.py # Concurrent test suite benchmarking
│   ├── common/                # Safe subprocess, .env manipulation, and colors
│   └── templates/             # Workspace and agent configuration templates
└── tests/                     # Automated test suites
```

---

## 📖 Practical Guide & Common Workflows

### 1. Multi-Repo Workspaces & Git Worktrees

Enables working across multiple decoupled repositories grouped under an isolated development space, utilizing Git worktrees to prevent redundant filesystem clones.

```bash
# Create an interactive multi-repo workspace
ws generate my-feature

# Create an isolated Git worktree for a specific branch
ws worktree /path/to/base-repo /path/to/target-worktree feature/new-api

# Modify repositories linked in an active workspace
ws edit my-feature

# Deep clean build caches and heavy artifacts (node_modules, .gradle, build/, dist/, .venv)
ws clean /path/to/workspace

# Reset repositories to upstream HEAD discarding local uncommitted changes
ws reset my-feature --force

# Delete a workspace and unregister its worktrees cleanly
ws delete my-feature
```

---

### 2. Local Microservices Orchestration (`ws run-local`)

Automatically discovers microservices in the workspace, allocates deterministic ports in the **8000–8999** range, rewrites inter-service endpoints (`wire_urls`), and launches an interactive TUI monitor.

```bash
# Launch services in the current workspace
ws run-local

# Launch with a specific execution profile and environment target
ws run-local --profile core-payments --env staging

# Stop all running background services
ws stop my-feature
```

**Interactive TUI Features**:
- Real-time process monitoring (PID, CPU, Memory, Port).
- Unified, selectable live log streaming per service.
- Individual and cascade service restarts without restarting unchanged services.
- Direct clickable links to local Swagger / OpenAPI documentation.

---

### 3. Git Hooks & Multi-Stack Quality Gate (`ws hooks`)

An automated, deterministic quality gate executed locally prior to every `git push` to catch issues before CI.

#### The 5 Quality Gate Stages
1. 🔒 **Security & Secrets**: Fast diff scan with `gitleaks` to block private keys, API tokens, JWTs, or accidental `.env` files.
2. 📝 **Git Policies**: Conventional Commits enforcement in imperative English and **ZERO AI mentions or robot emojis (🤖)**.
3. 🔍 **Static Analysis & Linters**: Stack auto-detection (Python/Ruff, Node/ESLint, Go/vet, Rust/clippy, Flutter/dart analyze).
4. 🧪 **Test Suites**: Execution of project unit tests (`pytest`, `jest`, `vitest`, `phpunit`, `mvn`, `gradle`, `cargo test`, `go test`).
5. 🪝 **Delegation to Repository Hooks**: Runs existing project hooks (Husky or custom hooks).

#### `ws hooks` Command Reference
```bash
# Diagnose local and global hook status
ws hooks status

# Install Quality Gate into local repository (.git/hooks/pre-push)
ws hooks install

# Install Quality Gate GLOBALLY across entire machine
ws hooks install --global

# Run Quality Gate on-demand (without pushing)
ws hooks run

# Run on changed files only or skip specific stages
ws hooks run --scope changed
ws hooks run --skip gitleaks,commits

# Test hook execution
ws hooks test

# Uninstall hooks (locally or globally)
ws hooks uninstall
ws hooks uninstall --global
```

---

### 4. Runtime, Build & Kubernetes Utilities

```bash
# Auto-detect stack and build (Maven, Gradle, NPM, Go, Python)
ws build

# Deterministically install project dependencies
ws deps

# Auto-configure JDK version via SDKMAN
ws java 21

# Interactively initialize and synchronize .env from .env.example
ws env-init
ws env-load

# Benchmark test suites with concurrent execution and Rich visual report
ws benchmark

# Kubernetes: Secure pod environment variable extraction (.env chmod 600)
ws kube env

# Kubernetes: Live pod log streaming (stern/tmux) and interactive shell
ws kube logs
ws kube shell
```


