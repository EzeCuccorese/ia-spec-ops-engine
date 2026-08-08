# Devscripts & SDD Toolkit

**The Single Source of Truth** for Spec-Driven Development (SDD), multi-repository workspace isolation, developer tooling, and engineering quality guidelines.

---

## 🌟 Key Capabilities

- **`sdd` CLI**: Spec-Driven Development CLI for rapid specification generation (`sdd spec`), plan execution (`sdd exec`), technical debt auditing (`sdd audit`), and project documentation (`sdd doc`).
- **Workspace Management**: Multi-repository isolation, workspace creation, editing, and synchronization scripts (`generate-workspace`, `edit-workspace`, `delete-workspaces`, `sync-toolkit`).
- **Developer Utilities**: Interactive TUIs and CLI tools for local service orchestration (`run-local`), multi-stack compilation (`build-project`), Kubernetes context management (`kube-env`), VPN controls (`toggle-vpn`), and service dashboards (`devscripts-dashboard`).
- **Agnostic Quality Rules**: Strict standards for Java/Spring Boot, Node.js/TypeScript, Python/FastAPI, React/JSX, databases, security, and git workflows.

---

## 🚀 Installation & Setup

### Prerequisites

- **OS**: macOS or Linux (bash/zsh)
- **Dependencies**: `python3` (3.10+ recommended), `git`, `curl`

### Step-by-Step Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Ezuser/devscripts.git
   cd devscripts
   ```

2. **Run the Modular Installer**:
   The installer supports three profiles: `--profile both` (default), `--profile only-sdd`, or `--profile only-tools`.

   ```bash
   # Install both SDD CLI and core developer tools into /usr/local/bin (or ~/.local/bin)
   ./install.sh --profile both
   ```

   *Optional Installer Options:*
   - `--prefix DIR`: Custom binary installation folder (e.g., `./install.sh --prefix ~/.local/bin`).
   - `--force`: Overwrite existing binaries without prompting.
   - `--uninstall`: Remove installed binaries and scripts cleanly.

3. **Verify Shell PATH Configuration**:
   If installed to `~/.local/bin` (or a custom prefix), ensure it is present in your PATH environment variable (`~/.zshrc` or `~/.bashrc`):
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```

4. **Verify Installation**:
   ```bash
   sdd --help
   ```

---

## ⚙️ Configuration & Project Setup

1. **Initialize SDD Structure in a Repository**:
   Navigate to your target project folder and run:
   ```bash
   sdd init
   ```
   This initializes the standardized [`.specify/`](.specify/README.md) directory structure (`.specify/constitution/`, `.specify/specs/`, `.specify/memory.md`, `.specify/tech-debt.md`).

2. **Synchronize Toolkit & Agnostic Rules**:
   To propagate updated skills and rules from `devscripts` to active workspaces:
   ```bash
   sync-toolkit
   ```

---

## 🏃 Quick Start Guide

### 1. Spec-Driven Development (`sdd` CLI)

- **Generate a Full Specification (Triad)**:
  ```bash
  sdd spec "Add user authentication endpoint with JWT validation"
  ```
- **Generate a Quick Spec**:
  ```bash
  sdd quick "Fix null pointer in order calculator"
  ```
- **Execute Implementation Plan**:
  ```bash
  sdd exec
  ```
- **Audit Technical Debt**:
  ```bash
  sdd audit
  ```
- **Generate / Fix Documentation**:
  ```bash
  sdd doc
  ```

### 2. Multi-Repo Workspaces

- **Create an isolated workspace**:
  ```bash
  generate-workspace
  ```
- **Edit repositories in workspace**:
  ```bash
  edit-workspace
  ```
- **Safely delete workspaces**:
  ```bash
  delete-workspaces
  ```

### 3. Core Developer Utilities

- **Interactive Service Dashboard**: `devscripts-dashboard`
- **Orchestrate Local Services**: `run-local`
- **Build Multi-Stack Projects**: `build-project`
- **Kubernetes Context TUI**: `kube-env`
- **Toggle VPN Connection**: `toggle-vpn`

---

## 📜 Development Rules & Quality Standards ([`rules/`](rules/README.md))

Central index for quality guidelines, engineering standards, and security policies:

- **[Development Rules Index](rules/README.md)** — Architectural overview and rule directory.
- **[Interaction & Working Style](rules/interaction.md)** — Chat formatting, bounded code edits, and mandatory pre-completion verification.
- **[Git Workflow & Commits](rules/git_workflow.md)** — Conventional Commits format, pre-push testing, and branch protection.
- **[Coding Practices](rules/coding_practices.md)** — Java/Spring Boot, Node.js/TypeScript, Python/FastAPI, React/JSX, and TDD standards.
- **[Databases & Storage](rules/databases.md)** — PostgreSQL & MongoDB access policies, mandatory JSON pre-write backup, and "OK WRITE" authorization.
- **[Data Migrations](rules/migrations.md)** — Parametric data migrations with Mongock `@ChangeUnit`, idempotency, and rollbacks.
- **[Observability](rules/observability.md)** — Structured logging levels, MDC context fields, and correlation headers (`X-Request-Id`, `X-Trace-Id`).
- **[Security & OWASP](rules/security.md)** — Secret leak prevention, system edge input validation, and OWASP dependency checks.
- **[Global Rules Index](config/rules-global/README.md)** — Global rule specifications applied across all managed repositories.

---

## 📚 Technical Documentation ([`docs/`](docs/))

Detailed guides on architecture, sidecar containers, database specifications, and platform orchestration:

- **[Specification Structure](.specify/README.md)** — Overview of `.specify/` directory structure and SDD workflow.
- **[Database Documentation Catalog](docs/database/README.md)** — Database schemas, entity relationships, and migration guides.
- **[SDD Architecture](docs/sdd-architecture.md)** — Technical design of Spec-Driven Development CLI and agents.
- **[Workspace Lifecycle](docs/run-workspace.md)** — Multi-repo creation, update, and synchronization lifecycle.
- **[Container Sandbox Execution](docs/agent-sandbox-startup-flow.md)** — Containerized isolation startup flow.
- **[Sidecar Container Architecture](docs/sidecar-architecture.md)** — Architecture of isolated container sidecars.
- **[Installer Sidecar Flow](docs/installer-sidecar-flow.md)** — Automatic dependency installation container workflow.
- **[Test Runner Sidecar Flow](docs/test-runner-sidecar-flow.md)** — Isolated test runner environment execution.
- **[Kubernetes Environment TUI](docs/kube-env.md)** — Guide for managing Kubernetes cluster environments.
- **[Dependency Caching](docs/dependency-caching.md)** — Volume caching strategy for build tools.
- **[Versioning & Releases](docs/versioning.md)** — Automated versioning with Release Please.
- **[Windows & Figma Setup](docs/windows-figma-setup.md)** — Setup instructions for Windows and design tooling.

---

## 🧪 Testing & Quality Assurance

Run the full pytest suite to verify toolkit integrity:

```bash
pytest
```
