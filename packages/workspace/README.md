# ia-spec-ops-engine workspace — Deterministic Workspace & Microservices Engine

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
│   ├── cli/                   # 19 subcommands unified by main.py
│   │   ├── main.py            # Master CLI dispatcher (`ws`)
│   │   ├── manage_hooks.py    # Subcommand `ws hooks`
│   │   ├── generate_workspace.py # Interactive multi-repo workspace generator
│   │   ├── create_worktree.py # Atomic Git worktree generator
│   │   ├── kube/              # Modular Kubernetes pod manager (`ws kube`)
│   │   └── ...
│   ├── config/                # `ws config` — workspace config.json bootstrapping
│   │   └── init_config.py     # Local/global/custom config generation
│   ├── integrations/claude/   # Coding-agent integration hooks (`ws hook ...`)
│   │   └── worktree_hook.py   # Claude WorktreeCreate destination suggestion
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
│   └── resources/             # Packaged workspace resources
│       ├── templates/         # .env.example / boilerplate templates for `ws env-init`
│       └── hooks/             # Canonical Git hooks (e.g. pre-push Quality Gate)
└── tests/                     # Automated test suites
```

---

## 📋 Subcommand Reference

| Command | Purpose |
| --- | --- |
| `ws generate` | Generate a new multi-repo workspace from Git worktrees |
| `ws edit` | Edit and add/remove repositories in an active workspace |
| `ws worktree` | Create an isolated Git worktree |
| `ws clean` | Clean dependencies, caches, and build artifacts in workspace |
| `ws stop` | Stop all running processes and services in workspace |
| `ws reset` | Reset workspace repositories to clean upstream state |
| `ws delete` | Delete workspaces and unregister associated worktrees |
| `ws build` | Build project auto-detecting the technology stack |
| `ws deps` | Install project dependencies (Gradle, Maven, NPM, uv, etc.) |
| `ws java` | Configure local Java JDK version via SDKMAN |
| `ws env-init` | Initialize repository environment files from templates |
| `ws env-load` | Load and inspect environment variables |
| `ws benchmark` | Execute parallel unit test benchmarks with visual reports |
| `ws run-local` | Orchestrate and launch local microservices with live TUI |
| `ws kube` | Kubernetes pod manager for environment extraction and shells |
| `ws hooks` | Multi-stack Git Hooks & Quality Gates manager |
| `ws check` | Run the quality gate with condensed output (`--changed`, `--cache`, `--json`) |
| `ws changed` | Files changed vs. the base branch |
| `ws design` | Per-function design/complexity metrics (`--changed`, `--files-from`, `--json`) |
| `ws run` / `ws log` / `ws condense` | Condensed command output and saved full logs |
| `ws detect` | Detect repository technology stacks |
| `ws hook` | Run a coding-agent integration hook |
| `ws doctor` | Verify system tools, compilers, and development environment |
| `ws config` | Initialize and manage workspace configuration |

---

## 📖 Practical Guide & Common Workflows

### 1. Multi-Repo Workspaces & Git Worktrees

Enables working across multiple decoupled repositories grouped under an isolated development space, utilizing Git worktrees to prevent redundant filesystem clones.

```bash
# Create an interactive multi-repo workspace
ws generate my-feature

# Create an isolated Git worktree for a specific branch
ws worktree /path/to/base-repo /path/to/target-worktree feature/new-api

# Claude WorktreeCreate hook: suggest a confined central location (never creates files)
export WORKSPACE_WORKTREES_DIR="$HOME/projects/worktree"
ws hook claude-worktree-create

# Modify repositories linked in an active workspace
ws edit my-feature

# Deep clean build caches and heavy artifacts (node_modules, .gradle, build/, dist/, .venv)
ws clean /path/to/workspace

# Reset repositories to upstream HEAD discarding local uncommitted changes
ws reset my-feature --force

# Delete a workspace and unregister its worktrees cleanly
ws delete my-feature
```

The Claude hook consumes the native JSON payload on stdin and is fail-open: malformed,
unsafe, or colliding inputs emit no suggestion and exit successfully. Suggested names are
sanitized and confined to `WORKSPACE_WORKTREES_DIR`; the hook itself never creates or removes
a worktree.

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

### 3. Git Hooks & Multi-Stack Quality Gate (`ws hooks`, `ws check`)

The gate is registered as **Git config-based hooks** (`hook.<name>.event/command`, Git with
`git hook list` support), never through `core.hooksPath`. Git runs them first and the
repository's own hooks (`.git/hooks`, Husky or any local `core.hooksPath`) last, so no project
hook of any type is shadowed, and the gate also runs in Husky repositories.

| Friendly name | Event | Checks |
|---|---|---|
| `workspace-pre-commit` | pre-commit | `gitleaks protect --staged` (skipped if gitleaks is absent) |
| `workspace-commit-msg` | commit-msg | Conventional Commits subject, max 100 characters |
| `workspace-gate` | pre-push | 5 stages: secrets (gitleaks), commit policies, linters, design limits, test suites |

Output is compact by default; a failing command keeps its full transcript at
`.git/workspace/quality-gate/latest.log` (`QG_OUTPUT=verbose` streams everything).
Skip stages with `QG_SKIP=gitleaks,commits,lint,design,tests`.

Stage 4, **design limits**, always runs `ws design --files-from <files in this push>`
regardless of `QG_SCOPE` — it judges new code, so it is always scoped to what is actually
being pushed. If `ws` is not on `PATH` it warns and passes rather than blocking the push.

```bash
ws hooks install            # this repository (keys in .git/config, scripts in .git/workspace/hooks)
ws hooks install --global   # every repository (keys in ~/.gitconfig, scripts in ~/.config/workspace/hooks)
ws hooks status             # registration status per scope
ws hooks uninstall [--global]  # removes only the workspace-* hook sections

ws check                    # run the gate now; condensed output, exit code preserved
ws check --changed --cache  # only changed files; skip if the tree is unchanged since the last pass
ws check --json             # versioned contract used by agent hooks
ws changed [--json]         # files changed vs. the base branch plus the working tree
```

### Design limits (`ws design`)

Measures every function's cyclomatic complexity, length (NLOC), parameter count and max
nesting depth via [lizard](https://github.com/terryyin/lizard) — one deterministic engine
covering Java, JavaScript/TypeScript/TSX/JSX, Python, Go, Kotlin, C#, PHP, Rust, Swift,
Scala, Ruby, C/C++ and more (priority for tests and docs here: Java, JS/TS, Python, Go,
then the rest). **Dart is not supported by lizard**, so `.dart` files are skipped.
Python's `self`/`cls` are not counted as parameters.

Defaults: `mode = "block"`, `max_complexity = 10`, `max_function_lines = 40`,
`max_args = 4`, `max_nesting = 3`. Vendored/generated paths are excluded by default
(`node_modules`, `vendor`, `dist`, `build`, `target`, `.venv`, `generated`, `*.min.js`).

Configure the optional `[design]` table in `<root>/.ai-governance/config.toml` — this is
the contract shared with ai-governance; `ws design` never reads or writes the repository's
own linter configs (eslint, checkstyle, ruff, golangci-lint, ...) to decide its limits:

```toml
[design]
mode = "warn"           # block | warn | off
max_complexity = 12
max_function_lines = 60
max_args = 5
max_nesting = 4
exclude = ["**/node_modules/**", "**/legacy/**"]
```

```bash
ws design                   # whole repo (git ls-files, or a walk without git)
ws design --changed         # only files changed vs. the base branch
ws design src/ pkg/foo.go   # specific files or directories
ws design --files-from list.txt  # newline-separated paths, relative to --dir
ws design --json            # versioned contract: {schema_version, status, violations, files}
```

Exit code is `1` on violations in `block` mode, `0` in `warn` or `off` mode (`off` prints
`design: off` and skips measuring).

**New vs. legacy code.** With `--changed` or `--files-from`, every violation is classified
`new` (its function overlaps lines added/modified since the merge-base, or its file is
untracked) or `legacy` (a pre-existing function in a touched file); a full, unscoped scan
marks everything `legacy`. Both fail in `block` mode, but the text report groups them —
"New code" first, then a "Pre-existing code" section whose header and footer push toward
a surgical fix instead of a rewrite: change only that function, keep behavior, add a
characterization test first, one function at a time. Each line ends with a metric-specific
hint (`complexity` → extract branches into named functions / guard clauses, `length` →
extract steps into well-named functions, `args` → introduce a parameter object, `nesting` →
return early, extract inner blocks). `--json` carries the same classification as an
`"origin": "new" | "legacy"` field per violation.

```bash
ws design --focus src/app/orders.py:142   # focused brief for the function at that line:
                                           # range, all four metrics vs. limits, pass/fail,
                                           # hints for the failing ones, numbered source
                                           # (capped at 120 lines). Exit 1 if it violates.
```

`ws design --focus <path:line>` is the surgical operation an agent runs right before
touching a flagged legacy function — confirm what's actually wrong and where, fix only
that, then move to the next one.

**Hygiene checks.** Alongside the four function metrics, `ws design` runs three
deterministic, line-based checks enforcing rule 01 ("never swallow exceptions") and
rule 11 ("self-documenting code") from the ai-governance catalog:

- `empty-catch` — a `catch`/`except`/error-check block whose body is empty or holds only
  comments: `catch (...) { }` (Java, Kotlin, JS/TS/TSX/JSX/MJS/CJS, C#, PHP, Dart, Swift,
  Scala), Python `except ...: pass`/`...` (via `ast`), Go `if err != nil { }`, Rust
  `Err(_) => {}` / `Err(_) => ()`.
- `todo-ticket` — a comment with `TODO`/`FIXME`/`XXX` and no ticket reference (a
  `PROJ-123`-style key, `#123`, or a URL).
- `commented-code` — a run of 2+ consecutive full-line comments that look like code (end
  with `;`, `{`, `}`, `)`, start with a statement keyword such as `return`/`if`/`def`/
  `class`/`const`, or, for Python, parse via `ast.parse` once dedented). Kept conservative
  to avoid flagging prose.

Each is a `Violation` with `value=1`, `limit=0`, the same new/legacy classification,
hints (`empty-catch` → handle, rethrow with context, or log with a reason; `todo-ticket` →
add a ticket reference or do it now; `commented-code` → delete it — version control
remembers), and the same text/JSON output and exit code as the other metrics. Toggle
which checks run with `[design].checks` in `.ai-governance/config.toml` (default: all
twelve); an unknown check name raises:

```toml
[design]
checks = ["complexity", "length", "args", "nesting", "empty-catch", "todo-ticket", "commented-code", "test-no-assert", "test-trivial-assert", "test-mock-only", "test-sleep", "test-duplicate"]
```

**Junk-test checks.** Five more deterministic checks enforce the ai-governance testing
rule ("a test must assert observable behavior"). They run only on test files (Java/Kotlin
`src/test/**` or `*Test(s).java|kt`/`*IT.java`; JS/TS `*.test.*`, `*.spec.*`,
`__tests__/**`; Python `test_*.py`, `*_test.py`, `tests/**`; Go `*_test.go`; C#
`*Tests.cs`; PHP `*Test.php`; Dart `*_test.dart`; Rust files with `#[test]`):

- `test-no-assert` — a test with no assertion (Java/Kotlin `@Test`/`@ParameterizedTest`,
  JS/TS `it(`/`test(`, Python `test_*` via `ast`, Go `func TestXxx(t *testing.T)`). Any
  assertion form counts, including `pytest.raises`/`warns`, `verify(`, `.rejects`,
  `t.Error*`/`t.Fatal*`, `assert.`/`require.` and calls to local helpers whose name starts
  with `assert`/`expect`/`check`/`verify`. Skipped or disabled tests are ignored.
- `test-trivial-assert` — an assertion that can never fail: `assert True`,
  `assertTrue(true)`, `expect(1).toBe(1)`, `assert x == x`, `assertEquals(a, a)` (same
  normalized expression on both sides, no calls).
- `test-mock-only` — every assertion of a test targets a mock (`verify(`, `then().should`,
  `toHaveBeenCalled*`, `assert_called*`, `mock.AssertExpectations`) and none checks a
  result or state.
- `test-sleep` — a real sleep: `Thread.sleep`, `time.sleep`, `await new Promise(r =>
  setTimeout ...)`, `await sleep(`, Go `time.Sleep` (best-effort for C#, PHP, Rust, Dart).
  Skipped in JS files that use fake timers.
- `test-duplicate` — a test whose body (3+ statements) equals an earlier test of the same
  file after normalizing whitespace, literals and local-variable names.

Hints: `test-no-assert` → assert the observable result or delete the test;
`test-trivial-assert` → assert real behavior; this can never fail; `test-mock-only` →
assert the result or state, not only the calls; `test-sleep` → inject a clock or poll with
a timeout; `test-duplicate` → merge into one parametrized test. A finding is `new` when any
line of the test is in the diff, `legacy` otherwise. Java, Kotlin, JS/TS, Python and Go are
the priority languages; the others get the sleep check only. To turn some off, list only
the checks you want in `[design].checks`, for example:

```toml
[design]
checks = ["complexity", "length", "args", "nesting", "empty-catch", "todo-ticket", "commented-code", "test-no-assert"]
```

**Layer boundaries (`architecture` profile).** With the ai-governance `architecture`
profile enabled (top-level `profiles = ["architecture"]` in `.ai-governance/config.toml`),
`ws design` also checks that inner layers never import outer ones — using its own
deterministic import scanner (no external tools) for Java, JS/TS/TSX/JSX/MJS/CJS, Python,
Go, then Kotlin, C#, PHP, Rust and Dart:

```toml
profiles = ["architecture"]

[design.layers]
# Ordered from outermost to innermost; a layer may import only itself and layers after it.
order = ["adapters", "application", "domain"]

[design.layers.paths]          # optional; default for a layer name X is ["**/X/**"]
adapters = ["**/adapters/**", "**/infrastructure/**"]
```

A file's layer is the first layer in `order` whose globs match its repo path; an import's
layer, the first layer whose globs match its resolved pseudo-path (relative specifiers are
resolved against the importing file; bare/package specifiers are ignored). A `domain` file
importing `adapters` is a `layers` violation (`domain → adapters (com.acme.adapters.Db)`),
hinted to depend on a port (interface) in the inner layer and implement it in the outer one;
it participates in the same new/legacy classification, text/JSON output and exit code as the
other metrics. With the profile on but `[design.layers]` missing, `ws design` prints
`layers: not configured ([design.layers])` and does not fail.

### Condensed command output for agents (`ws run`, `ws log`, `ws condense`)

```bash
ws run -- mvn test          # runs, keeps the exit code, prints a condensed summary
ws log <id> --grep ERROR    # read the saved full output (0600, 7 days / 200 logs)
ws log <id> --lines 120-180
ws condense --command "pytest" --json < output.txt   # contract used by ai-governance hooks
```

The condenser is deterministic: tool profiles (pytest, jest/vitest, go, cargo,
maven/gradle, linters) keep the summary and every failure with context; ANSI codes,
progress bars, timestamps and repeated lines are removed; successful runs collapse to one
line; output never exceeds the character budget.

### Stack detection (`ws detect`)

`ws detect [--json]` reports stacks (java, kotlin, node, typescript, react, python, go, rust,
php, flutter, dotnet, docker, kubernetes, sql, migrations, github-actions, gitlab-ci, jenkins)
from marker files. ai-governance uses it to install only the rules a project needs.

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

---

### 5. Workspace Configuration (`ws config`)

Bootstraps the `config.json` that `ws` reads for project naming, namespaces, and
(optionally) enterprise environments/VPN settings. Written project-locally
(`.workspace/config.json`) or user-globally (under `XDG_CONFIG_HOME`, see below).

```bash
# Interactively initialize project-local configuration
ws config init --local

# Non-interactive, user-global configuration
ws config init --global --yes --name my-project --domain my-domain.io

# Full enterprise profile (environments, VPN, ArtifactRegistry placeholders)
ws config init --local --enterprise --yes

# Write to a custom path instead
ws config init --path ./custom-config.json --yes

# Overwrite an existing configuration without confirmation
ws config init --local --force --yes
```

`ws config` currently exposes a single subcommand, `init`; run `ws config --help`
or `ws config init --help` for the full, up-to-date list of subcommands and flags.

---

## ⚙️ Configuration & Environment Variables

| Variable | Used by | Description | Default |
| --- | --- | --- | --- |
| `AI_REPOSITORIES_DIR` | `ws generate`, `ws edit` | Directory containing local project repositories used when wiring up a new/edited workspace. | none (falls back to values already present in the workspace's `.env`) |
| `WORKSPACE_WORKTREES_DIR` | `ws hook claude-worktree-create` | Confines suggested Git worktree destinations for the Claude WorktreeCreate integration hook; suggestions are sanitized and never leave this directory, and the hook never creates the worktree itself. | `~/projects/worktree` |
| `XDG_CONFIG_HOME` | `ws config init` (global scope), config discovery | Base directory for the user-global workspace configuration file. | `~/.config` (i.e. config lives at `~/.config/workspace/config.json`) |
| `JAVA_HOME` | `ws run-local` (process manager) | JDK home used when launching Java-based services locally. | whatever is already set in the environment; unset means the system default `java` is used |
| `QG_OUTPUT` | `ws hooks run` / the installed `pre-push` Quality Gate hook | Controls verbosity of Quality Gate output: `errors` hides successful command output, `verbose` streams every command live. | `errors` |

Package-manager cache locations (`YARN_CACHE_DIR`, `GRADLE_CACHE_DIR`, `M2_CACHE_DIR`,
`NPM_CACHE_DIR`) and AWS/ArtifactRegistry placeholders (`AWS_PROFILE`, `AWS_CONFIG_FILE`,
`AWS_DEFAULT_REGION`, `ARTIFACT_REGISTRY_DOMAIN`, `ARTIFACT_REGISTRY_DOMAIN_OWNER`) are
project-level conventions read from generated `.env` files rather than by the
`workspace_engine` package itself — see `config/.env.example` at the repo root.
