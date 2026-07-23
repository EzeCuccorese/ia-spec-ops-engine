# DevScripts & AI Workspace Toolkit

Herramientas unificadas de desarrollo, automatización y orquestación de workspaces de IA. Combina utilidades individuales para el flujo de trabajo diario de desarrollo con la infraestructura para Specification-Driven Development (SDD) con agentes IA.

## Funcionalidades Principales

1. **Dashboard TUI Unificado**: Ejecuta todas las herramientas desde un panel centralizado (`python3 dashboard.py` o `./toolkit-menu.sh`).
2. **Automatización de Desarrollo**:
   - `python3 run-local.py`: Ejecutor interactivo de microservicios locales (Spring / Node / Go).
   - `python3 kube-env.py`: Gestión interactiva TUI de pods en Kubernetes (env vars, logs, exec, restart).
   - `python3 build-project.py`: Compilación y configuración de versión Java (Maven/Gradle via SDKMAN).
   - `python3 toggle-vpn.py`: Gestión de sesiones OpenVPN3.
   - `python3 load-env.py`: Actualización de variables de entorno en YAMLs de GitOps.
3. **Orquestación de Workspaces de IA**:
   - `./generate-workspace.sh`: Creación de workspaces con worktrees de Git aislados.
   - `./sync-toolkit.sh`: Sincronización de scripts, plantillas y skills hacia los workspaces.
   - `./claude-yolo.sh`: Entorno Docker sandbox seguro.

---

## Directory structure

The toolkit expects a specific layout on your machine. All three directories live as siblings under a common parent:

```
<parent>/                         ← any directory of your choice
├── ai-dev-toolkit/              ← this repo (cloned once)
├── repositories/                 ← all AI repos cloned here (set as AI_REPOSITORIES_DIR)
└── workspaces/                   ← generated automatically by generate-workspace.sh
    ├── my-feature/
    ├── another-task/
    └── ...
```

`workspaces/` is created the first time you run `generate-workspace.sh` — you don't need to create it manually. The `AI_REPOSITORIES_DIR` in `config/.env` should point to your repos folder (absolute path recommended).

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Docker** | Must be installed and the daemon must be running. **Linux:** use [Docker Engine](https://docs.docker.com/engine/install/) (not Docker Desktop) — see [Linux users](#linux-users) below. **macOS / Windows:** [Docker Desktop →](https://docs.docker.com/get-docker/) |
| **Python 3** | Required for workspace orchestration scripts. Ships with macOS 12+ and most Linux distros. |
| **Bash 3.2+** | macOS system bash is sufficient. |
| **AWS SSO** | Required for any task that needs ArtifactRegistry: `install-deps.sh`, the `/ai-implement-ticket` skill (Step 0), and test runs that install dependencies. Needs the `example-dev` profile in `~/.aws/config`. |
| **jq** | Required by `docker/scripts/run-unit-tests.sh` for JSON payload construction and exit-code parsing. |
| **rsync** | Required by `sync-toolkit.sh` to propagate toolkit changes into workspaces. |
| **WSL 2 + Ubuntu** (Windows only) | All scripts must run from inside WSL — not from PowerShell or CMD. [Install WSL →](https://learn.microsoft.com/en-us/windows/wsl/install) |

### Platform compatibility

| Host | `claude` (supported) | `claude-yolo` (experimental) |
|------|----------------------|-------------------------------|
| macOS | ✅ | ✅ |
| Linux | ✅ | ✅ |
| Windows + WSL2 ¹ | ✅ | ✅ |
| Windows native / Git Bash | ❌ Not supported | ❌ Not supported |

¹ On Windows the **only** supported configuration is WSL2. The toolkit and the
work repos must live in the **WSL filesystem** (e.g. `~/dev/...`), not on the
Windows drive (`/mnt/c`) — otherwise Docker, installs, and git are slow and git
hits filemode/CRLF footguns. Use your IDE in **Remote-WSL** mode; a native-Windows
git GUI over `\\wsl$` reintroduces the same boundary slowness. `generate-workspace`
refuses native-Windows and `/mnt` layouts. A one-time Figma MCP bridge is still
needed when Claude runs inside WSL2/Docker — see
[`docs/windows-figma-setup.md`](docs/windows-figma-setup.md).

A Docker-compatible engine is required for the test-runner sidecar. The toolkit is
engine-agnostic: it follows your active `docker context` (and `DOCKER_HOST`) for both
host commands and the sidecar's Docker-out-of-Docker mounts, so it does not assume a
specific socket path. On **macOS** any of Docker Desktop, [OrbStack](https://orbstack.dev/),
or [Colima](https://github.com/abiosoft/colima) work — OrbStack/Colima are much lighter
than Docker Desktop; just make sure the engine you want is the active context
(`docker context use <name>`). On **Windows** use Docker Desktop with WSL2. On **Linux**
use Docker Engine — see [Linux users](#linux-users) below.

### Linux users

Use **Docker Engine** (native `dockerd`), not Docker Desktop. Docker Desktop on Linux runs inside a VM and uses virtiofsd for bind mounts — under I/O load this can crash the VM and make the Docker socket unavailable. Docker Engine runs bind mounts directly through the kernel: no VM, no virtiofsd, no instability.

1. **Install Docker Engine** following the [official guide for your distro](https://docs.docker.com/engine/install/).

2. **Add your user to the `docker` group** so you can run `docker` without `sudo`:
   ```bash
   sudo usermod -aG docker $USER
   # Then log out and back in (or run: newgrp docker)
   ```

3. **Verify:**
   ```bash
   docker info
   ```

If you already have Docker Desktop installed, uninstall it and switch the Docker context to the system daemon:
```bash
docker context use default
```

### Windows users (WSL)

All toolkit scripts must run from a **WSL 2 terminal** (Ubuntu recommended), not from PowerShell or Command Prompt.

1. **Install WSL 2** if not already installed:
   ```
   wsl --install
   ```
   Then open the Ubuntu app and complete the initial setup.

2. **Clone the toolkit inside WSL**, not on the Windows filesystem:
   ```bash
   # Good — fast, Linux-native
   cd ~
   git clone git@github.com:example-corp/ai-dev-toolkit.git

   # Avoid — the /mnt/c/ filesystem is much slower and can cause permission issues
   cd /mnt/c/Users/you/projects
   ```

3. **Use Linux paths** everywhere. When `init-env.sh` asks for `AI_REPOSITORIES_DIR`, provide the WSL path:
   ```
   /home/youruser/repos        ← correct
   /mnt/c/Users/you/repos      ← works but slow; avoid if possible
   C:\Users\you\repos          ← never use Windows paths in WSL scripts
   ```

4. **Docker Desktop** must have WSL 2 integration enabled. In Docker Desktop → Settings → Resources → WSL Integration, enable your Ubuntu distro.

5. **VPN routing** is set up automatically the first time you run `claude-yolo.sh`. If your VPN runs on Windows (not inside WSL), containers may not reach internal services — see the warning printed by `claude-yolo.sh` for instructions on enabling WSL mirror networking mode.

---


## Core concepts

**Workspaces** are directories at `../workspaces/<name>/` that contain:
- Git worktrees for each selected repo (lightweight, no clone overhead)
- Real directory copies of `scripts/`, `docker/`, and `.claude/` from the toolkit (`config/` is the only symlink — machine-level shared config)
- An isolated `.claude/` with workspace-specific skills and memory

**`.claude/` is a fresh directory with copied subdirs.** At creation time a new `.claude/` is created in the workspace and its subdirectories (`skills/`, `agents/`, `hooks/`, `scripts/`) are copied from `agents/claude/` in the toolkit. Run `sync-toolkit.sh` to propagate toolkit updates to existing workspaces. Each workspace also gets a generated `settings.json` that registers the boundary enforcement hook (see below).

**Boundary enforcement** is automatic. Each workspace gets a `settings.json` that registers a PreToolUse hook (`enforce-repo-boundary.sh`). The hook blocks Claude from writing files or running `git add`/`git commit` outside `repositories/` — preventing accidental modifications to workspace infrastructure.

**Parallel workspaces** are fully supported — each workspace has its own branch per repo, its own `.claude/` copy, and its own Docker container scope. You can run multiple features simultaneously without interference.

**Scope limiting** is intentional. When creating a workspace you select only the repos relevant to the task. Claude Code only sees those repos, keeping context small and focused.

**Branch naming**: the workspace name becomes the default branch name for all selected repos. You can override this per repo in the TUI.

---

## Setup

### First-time setup

```bash
./scripts/init-env.sh
```

That's it. The script creates `config/.env` and `config/.env.secrets` from their examples if they don't exist, then prompts interactively for any unset variables in `.env`.

`config/.env.secrets` is created automatically but its values must be filled in manually — open it and set `JIRA_USER` and `JIRA_API_KEY`. It's also safe to re-run `init-env.sh` at any time to fill in missing variables or update existing ones.

---

## Toolkit menu (TUI)

Not sure which script to run? `./toolkit-menu.sh` opens an interactive
[Textual](https://textual.textualize.io/) menu listing every user-facing script with a
description, its flags, and a danger badge (safe / caution / destructive).

```bash
./toolkit-menu.sh
```

- **Context-aware**: detects whether you're at the toolkit root or inside a workspace and
  lists only the scripts that apply there (the rest are hidden, not greyed out).
- **Flag editor**: pick a script and toggle its flags / fill in args; it previews the exact
  command before running.
- **How it runs**: non-interactive scripts stream their output inside the TUI; interactive
  ones (e.g. `generate-workspace.sh`) suspend the TUI and run on the real terminal, then
  return to the menu. `caution`/`destructive` scripts ask for confirmation first.

The script catalog lives in `bin/toolkit-menu/scripts.json` (edit it to add or retune
entries). `toolkit-menu` needs the **`textual`** package; unlike `rich` for the other
Python TUIs, it is **auto-provisioned** on first launch into a managed virtualenv at
`.ai-toolkit/venv` (PEP 668-safe — never touches your system/Homebrew Python). No manual
install step needed. If provisioning is impossible (no network, no venv module), the
launcher prints a clear actionable error and exits non-zero.

---

## Daily workflow

For every new task or Jira ticket, three commands get you into a working session:

```bash
# 1. From the toolkit root — create a workspace for the task
./generate-workspace.sh

# 2. Enter the workspace
cd ../workspaces/<name>

# 3. Launch Claude Code
claude
```

> **Experimental:** `./scripts/claude-yolo.sh` runs Claude inside a sandboxed Docker container with automatic dependency installation and a test-runner sidecar. See [claude-yolo — the dev container](#claude-yolo--the-dev-container-experimental).

To launch the workspace services locally (Spring / Node / Next.js / Vite) with envs extracted from the cluster pod and automatic wire-up of inter-service URLs, use `./scripts/run-workspace.py` and `./scripts/stop-workspace.sh`. Full guide with diagrams in [`docs/run-workspace.md`](./docs/run-workspace.md).

When done, delete the workspace from the toolkit root or from inside the workspace:

```bash
./delete-workspaces.sh
```

To add or remove repositories from an existing workspace, run from inside it:

```bash
./edit-workspace.sh
```

---

## Create a workspace

```bash
# Interactive — TUI with arrow-key navigation, SPACE to toggle repos, ESC to cancel
./generate-workspace.sh

# Direct — workspace name + repos
./generate-workspace.sh my-feature valiant-rural-productor gres-grecosystem-bff
```

The TUI lets you select repos and optionally configure a branch per repo (press `→` on any entry to open the branch config panel). Selected repos become Git worktrees at `workspace/repositories/<repo>`.

---

## Launch Claude

```bash
cd ../workspaces/my-feature
claude
```

This is the supported way to start a session. Claude Code runs directly on the host with full access to the workspace's `.claude/` skills, hooks, and config.

### claude-yolo (experimental)

```bash
./scripts/claude-yolo.sh
```

An experimental alternative that runs Claude inside a sandboxed Docker container. On startup it:
1. Starts an **installer sidecar** to check and install missing dependencies
2. Starts a **test-runner sidecar** for running unit tests
3. Launches Claude in `--dangerously-skip-permissions` mode

---

## Install dependencies

Run from inside a workspace to install dependencies for all repos:

```bash
# All repos
./scripts/install-deps.sh

# Single repo
./scripts/install-deps.sh valiant-rural-productor

# Force AWS SSO re-login (when ArtifactRegistry token is expired)
./scripts/install-deps.sh --force-login
```

Per-repo logs are written to `workspace/.ai-toolkit/install-logs/<repo>.log`. The terminal shows only status lines; full output is in the log file.

In `claude-yolo` mode this runs automatically on startup — you rarely need to invoke it manually.

---

## Edit a workspace

Run from inside a workspace to add or remove repositories:

```bash
./edit-workspace.sh
```

- **Add**: same repo + branch selection TUI as `generate-workspace.sh`. Repos already in the workspace appear dimmed and locked — to re-add one with a different branch, remove it first. Adds new worktrees and updates `.ai-toolkit/workspace.json` and `CLAUDE.md`.
- **Remove**: select one or more repos from the workspace. Checks for uncommitted changes and unpushed commits before removing. Removes worktrees, deletes branches (only if fully pushed), updates `.ai-toolkit/workspace.json` and `CLAUDE.md`.

ESC at any step cancels without changes.

---

## Delete workspaces

From the **toolkit root** (`ai-dev-toolkit/`), opens an interactive TUI to select one or more workspaces to delete:

```bash
./delete-workspaces.sh
```

From **inside a workspace**, skips the TUI and deletes that workspace directly after a `[y/N]` confirmation:

```bash
./delete-workspaces.sh
```

Both modes check for uncommitted changes and unpushed commits before removing worktrees, deleting branches (only if fully pushed), and removing the workspace directory.

---

## Keeping the toolkit up to date

### Update the toolkit

Run from the toolkit root to pull the latest stable release:

```bash
./update-toolkit.sh
```

After checkout the repo will be in **detached HEAD** — that is expected. You are on a frozen release tag; do not commit from this state. See `CHANGELOG.md` for what changed.

### Sync workspaces

After updating the toolkit, push the changes to existing workspaces:

```bash
# From the toolkit root — syncs all workspaces at once
./sync-toolkit.sh

# From inside a workspace — syncs just that one
./sync-toolkit.sh
```

This copies updated `scripts/`, `docker/`, and `.claude/` (skills, hooks, scripts) into each workspace and regenerates `settings.json` and `CLAUDE.md`.

### Release channels

The toolkit follows SemVer. Two channels are available:

- **Stable** (`vX.Y.Z`) — the default. Tested and ready for daily use.
- **Beta** (`vX.Y.Z-beta.N`) — rolling previews. Only the latest beta tag is supported.

```bash
./update-toolkit.sh --beta                      # latest beta tag
./update-toolkit.sh --version v1.3.0-beta.2    # specific tag
./update-toolkit.sh --status                    # show current ref
./update-toolkit.sh --list                      # list all available tags
```

Beta releases may contain breaking changes. Run `--beta` again to advance to the latest.

For release internals and the maintainer runbook see [`docs/versioning.md`](./docs/versioning.md). For a full history of changes see [`CHANGELOG.md`](./CHANGELOG.md).

---

## Configuration

### config/.env

| Variable | Description |
|----------|-------------|
| `AI_REPOSITORIES_DIR` | Path to local AI repos. Absolute or relative to toolkit root. |

### config/.env.secrets

| Variable | Description |
|----------|-------------|
| `JIRA_USER` | Atlassian account email |
| `JIRA_API_KEY` | Atlassian API token |

`ARTIFACT_REGISTRY_AUTH_TOKEN` is **not** stored here — it is acquired at runtime via `aws artifact_registry get-authorization-token` using the `example-dev` SSO profile.

---

## Directory layout

```
ai-dev-toolkit/
├── generate-workspace.sh       # create workspaces (interactive or direct)
├── edit-workspace.sh           # add or remove repos in the current workspace
├── delete-workspaces.sh        # delete workspaces with safety checks
├── scripts/                    # copied into every workspace
│   ├── claude-yolo.sh          # launch Docker dev container
│   ├── install-deps.sh         # install repo dependencies (local or sidecar)
│   ├── init-env.sh             # first-time (or repeat) config/.env setup
│   ├── unit-test-benchmark.sh  # cold/warm unit-test benchmark across the workspace (+ -display.py companion)
│   └── kube-env.py             # Kubernetes pod env TUI
├── docker/
│   ├── claude-yolo/            # Dockerfile, entrypoint, firewall script
│   ├── docker-local/           # host-only test-runner implementation + lib helpers
│   │   ├── docker-run-unit-tests.sh  # persistent-container test runner (called by proxy)
│   │   ├── stop-test-runners.sh      # host-mode stop, requires --workspace
│   │   ├── lib/                      # detect_test_cmd.py, find_port.py, select_dockerfile.py
│   │   └── tests/                    # bats suite
│   ├── test-runner/            # test-runner sidecar (server.py, Dockerfile, sidecar.sh)
│   ├── installer/              # installer sidecar — deps install system
│   │   ├── Dockerfile
│   │   ├── install-workspace.sh, ensure-deps.sh, detect-project-type.sh, detect-node-pm.sh, needs-install.sh
│   │   ├── aws-auth/           # ensure-token.sh, kube-token.sh, probe-artifact_registry.sh
│   │   └── installers/         # install-node.sh (yarn/pnpm/npm), install-gradle.sh, install-maven.sh
│   └── scripts/                # host-side utilities + dual-mode test entrypoints
│       ├── docker-utils.sh
│       ├── run-unit-tests.sh   # always routes through test-runner sidecar (host mode lazy-starts it)
│       ├── stop-test-runners.sh # context-aware cleanup (claude-yolo vs host)
│       └── tests/              # bats suite
├── bin/
│   ├── generate-workspace/     # generate_workspace.py, select_repos.py, configure_workspace_repos.py
│   └── workspace-claude.md.template  # rendered into each workspace's CLAUDE.md
├── config/                     # .env, .env.secrets (gitignored)
└── agents/
    └── claude/                 # copied into each workspace's .claude/ at generate/sync time
        ├── skills/             # ai-plan-ticket, ai-implement-ticket, ai-fixup-pr-comments, ai-constitution
        ├── agents/             # subagent definitions (e.g. ai-tdd-implementer) — copied into workspace .claude/agents/
        ├── hooks/              # PreToolUse hooks — enforce-repo-boundary.sh
        ├── scripts/            # jira-get.sh, jira-update.sh, jira-attachment.sh, session-cost.sh
        └── model-costs.json    # pricing data
```

## Running tests

From inside a workspace, use `docker/scripts/run-unit-tests.sh`. It always routes through the test-runner sidecar — inside `claude-yolo` the sidecar is already running on the workspace network; in host mode it is lazily started with an ephemeral `127.0.0.1` port. The inner scripts in `docker/docker-local/` are the sidecar's internal implementation — never invoke them directly.

```bash
# Full test suite
./docker/scripts/run-unit-tests.sh --repo ms-orders-transitions

# Single test (pattern translated per runner)
./docker/scripts/run-unit-tests.sh --repo ms-orders-transitions --test-file "TestHandleRequest"

# Override the test command entirely
./docker/scripts/run-unit-tests.sh --repo ms-orders-transitions --cmd "go test -v ./internal/..."

# Stop all test containers managed by the sidecar
./docker/scripts/stop-test-runners.sh
```

`--test-file <filter>` is translated automatically per runner:

| Stack | Command |
|-------|---------|
| Node.js (npm) | `npm test -- <filter>` |
| Node.js (yarn) | `yarn test <filter>` |
| Gradle | `./gradlew test --tests "<filter>"` |
| Maven | `mvn test -Dtest=<filter>` |
| Go | `go test -v -run <filter> ./...` |

Test logs are written to `workspace/.ai-toolkit/test-logs/<log_id>.log` — accessible both on the host and inside the running container.

Repos with no detectable test suite (`unknown` project type — no `package.json`, `build.gradle`, `gradlew`, `pom.xml`, or `go.mod`) exit 0 immediately with a green message. No special handling needed in callers. Go repos (`go.mod`) run `go test` in a `golang` container with `GOPROXY=off`: the installer resolves modules ahead of time (`go mod download` into the shared `$HOME/go` cache), so the test run only reads the cache and never pulls dependencies over the network.

### Benchmarking test execution

`scripts/unit-test-benchmark.sh` runs the test suite of one, many, or all repos in the current workspace through the test-runner sidecar and reports per-phase wall-time (install / build / cold / warm) plus pass counts, in a live rich TUI and a final table.

```bash
# Pick repos interactively (TUI)
./scripts/unit-test-benchmark.sh

# Every repo, 4 in parallel, cold + warm runs
./scripts/unit-test-benchmark.sh --all --repeat --parallel 4

# Specific repos
./scripts/unit-test-benchmark.sh ms-orders-transitions valiant-rural-productor

# Re-render the last run's table without re-running
./scripts/unit-test-benchmark.sh --result
```

It is a **cold** benchmark: init runs `scripts/clean-workspace.sh`, wiping `node_modules`/`.gradle`, `.ai-toolkit/` (except `workspace.json`), and the per-repo VM-native Docker volumes (`ai-node-modules-<workspace>-<repo>`) — those volumes shadow the host dirs inside the containers, so without dropping them the install reports "Already up-to-date" instead of running cold. So install and build are measured from scratch — git-tracked source is never touched. Per-repo logs and `summary.tsv` land in `.ai-toolkit/unit-test-benchmark/`.

---

## claude-yolo — the dev container (experimental)

`claude-yolo.sh` builds and runs two separate Docker images. Each is tagged by the content hash of its own source files and rebuilds automatically when those files change. Both images are shared across all workspaces on the same machine.

### Workspace container — `claude-yolo:<hash>`

Built from `docker/claude-yolo/`. Runs Claude Code in `--dangerously-skip-permissions` mode.

| Tool | Version |
|------|---------|
| Node.js | 22 |
| Claude Code | latest |
| GitHub CLI (`gh`) | latest |
| bubblewrap | latest |
| socat | latest |

### Installer sidecar — `ai-installer:<hash>`

Built from `docker/installer/` + `docker/scripts/`. Ephemeral — starts before the workspace container, installs any missing dependencies, then stops. Owns all AWS credential management and package installation so those tools never enter the workspace container.

| Tool | Version |
|------|---------|
| Node.js | 22 |
| yarn | latest |
| Java JDK | 17 (headless) |
| Maven | 3.x |
| Gradle | 8.7 |
| AWS CLI | v2 |
| kubectl | latest stable |

### Test-runner sidecar — `ai-test-runner:<hash>`

Built from `docker/test-runner/`. Runs for the full workspace session alongside the workspace container. Manages persistent per-repo test containers, streams test output over HTTP, and writes per-invocation logs to `.ai-toolkit/test-logs/`.

| Tool | Version |
|------|---------|
| Python 3 | system (bookworm) |
| Docker CLI | latest |

```
Host
 ├── workspace container    (claude-yolo)       ← Claude Code runs here
 ├── installer sidecar      (ai-installer)    ← token refresh, yarn/gradle/mvn install
 │       └── ~/.aws (read-only mount for SSO token cache)
 └── test-runner sidecar    (ai-test-runner)  ← persistent test containers per repo
         ├── /var/run/docker.sock (spawns test containers on host Docker)
         └── ~/.cache, ~/.gradle, ~/.m2, ~/.npm (forwarded to test containers)
```

Dependency installation runs automatically via the installer sidecar on startup. The installer sidecar is started by `claude-yolo.sh` and stopped when the workspace container exits. The test-runner sidecar runs alongside the workspace container for the full session and is stopped on exit.

---

## Bash compatibility

All bash scripts are compatible with **bash 3.2** (macOS system bash). No associative arrays, no decimal timeouts. Workspace orchestration (`generate_workspace.py`, `select_repos.py`, `configure_workspace_repos.py`) is Python 3 stdlib only.
