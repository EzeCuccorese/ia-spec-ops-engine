# cucco-workspace — Deterministic Workspace & Microservices Engine

Autonomous subproject for managing development workspaces, Git worktrees, dependencies, multi-stack builds, JDK configuration, local microservices orchestration (`run-local`), Kubernetes debugging (`kube`), and Git quality gates (`ws hooks`).

---

## 🚀 Key Features

1. **Workspace & Worktree Management**:
   - `ws generate`: Deterministic creation of multi-repo workspaces with Git worktrees.
   - `ws edit`: Interactive addition and modification of repositories within an active workspace.
   - `ws worktree`: Atomic Git worktree generation for isolated branch development.
   - `ws clean`: Deep cleaning of build artifacts (`node_modules`, `.gradle`, `build/`, `dist/`, `.venv`).
   - `ws reset`: Reset repositories to upstream HEAD or base commit.
   - `ws stop`: Safe termination of running background services.
   - `ws delete`: Deletion of workspaces and unregistration of worktrees.

2. **Git Hooks & Quality Gate Manager (`ws hooks`)**:
   - `ws hooks status`: Visual diagnosis of local and global Git hooks.
   - `ws hooks install [--global]`: Installation of 4-stage Quality Gate (Secret scan, Zero AI mentions, Linters, Tests).
   - `ws hooks uninstall [--global]`: Clean uninstallation and unbinding of hooks.

3. **Runtime & Build Tools**:
   - `ws build`: Multi-stack compilation (Maven, Gradle, Node, Go, Python).
   - `ws deps`: Deterministic host dependency installation.
   - `ws java`: Automatic JDK version detection and configuration via SDKMAN.
   - `ws env-init` / `ws env-load`: Interactive `.env` synchronization from `.env.example`.
   - `ws benchmark`: Parallel test suite benchmark execution with visual reporting.
   - `ws doctor`: Development environment diagnostic tool.

4. **Local Microservices Orchestrator (`ws run-local`)**:
   - Automatic service discovery and deterministic local port allocation (8000–8999).
   - URL re-writing (`wire_urls`) from remote endpoints to local ports.
   - Interactive TUI monitor with live log streaming, cascade restarts, and Swagger links.

5. **Kubernetes Environment Manager (`ws kube`)**:
   - Interactive TUI for pod environment extraction (`.env`, `set-env.sh`) with `chmod 600` permissions.
   - Stern/Tmux live log streaming and interactive shell access.

---

## 🛠️ CLI Reference Table (`ws`)

| Command | Description |
|---|---|
| `ws doctor` | Diagnoses installed tools, compilers, and development runtimes |
| `ws hooks` | Git Hooks & Quality Gate manager (`install`, `status`, `uninstall`) |
| `ws generate` | Generates a new multi-repo workspace from Git worktrees |
| `ws edit` | Edits active workspace repositories |
| `ws worktree` | Creates an atomic worktree for a branch |
| `ws clean` | Cleans caches and build artifacts across workspace |
| `ws stop` | Stops running services in the workspace |
| `ws reset` | Resets repositories to upstream clean state |
| `ws delete` | Deletes workspace and cleans worktrees |
| `ws build` | Builds projects (Maven, Gradle, Node, Go, Python) |
| `ws deps` | Installs local repository dependencies |
| `ws java` | Configures matching JDK version via SDKMAN |
| `ws env-init` | Interactively initializes `.env` files |
| `ws env-load` | Loads and inspects environment variables |
| `ws benchmark`| Executes test benchmarks with visual reports |
| `ws run-local`| Orchestrates and launches microservices locally |
| `ws kube` | Interactive TUI for Kubernetes pod inspection |
