# ia-spec-ops-engine workspace — Deterministic Workspace & Microservices Engine

**Workspace Engine (`ws`)** is the deterministic orchestrator for local development environments, multi-repository Git worktree isolation, multi-stack builds and dependency management, local/global pre-push Quality Gates, and microservices runtime supervision with an interactive TUI.

---

## 🎯 Purpose & Overview

Developing modern distributed systems and microservices architectures poses recurring challenges:
- Managing multiple interconnected repositories concurrently without polluting branches or duplicating entire workspace directories.
- Spinning up 5 to 10 microservices locally while manually resolving port collisions and inter-service endpoints.
- Leaking secrets, lint errors, or failing tests into upstream branches, causing CI failures.
- Inconsistent JDK, Node, or environment variable versions across development machines.

`ws` automates and unifies these workflows under a single, deterministic CLI interface.

---

## 💻 Installation & Setup

### 1. Installation
From the monorepo root:

```bash
# As a global tool (recommended)
uv tool install ./packages/workspace

# Or editable, into an existing environment
uv pip install -e packages/workspace
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

```
packages/workspace/
├── src/workspace_engine/
│   ├── cli/                   # Subcommand entry points dispatched by main.py
│   │   ├── main.py            # Master CLI dispatcher (`ws`)
│   │   ├── check.py           # `ws check` / `ws changed`
│   │   ├── design.py          # `ws design`
│   │   ├── manage_hooks.py    # `ws hooks`
│   │   ├── create_worktree.py # `ws worktree`
│   │   ├── kube/              # Kubernetes pod manager (`ws kube`)
│   │   └── ...                # generate, edit, clean, stop, reset, delete, build, deps, java, env-*, benchmark
│   ├── condense/              # `ws run` / `ws condense` / `ws log`: deterministic condenser and private log store
│   ├── design/                # `ws design`: lizard metrics, hygiene, junk-test and layer checks, merge-base ratchet
│   ├── config/                # `ws config init` — workspace config.json bootstrapping
│   ├── integrations/claude/   # Coding-agent integration hooks (`ws hook ...`)
│   │   └── worktree_hook.py   # Claude WorktreeCreate destination suggestion
│   ├── run_local/             # `ws run-local`: discovery, ports (8000-8999), URL wiring, process manager, TUI
│   ├── services/              # Stack detection, change sets, Git hooks/quality gate, repository helpers
│   ├── common/                # Safe subprocess, .env parsing, colors and agent-mode output
│   └── resources/
│       ├── hooks/             # Git hook scripts: pre-commit, commit-msg, pre-push (quality gate)
│       └── templates/         # Workspace AGENTS.md template used by `ws generate`
├── tests/                     # Unit and acceptance tests
└── tests_integration/         # End-to-end tests
```

---

## 📋 Subcommand Reference

| Command | Purpose |
| --- | --- |
| `ws generate [name] [repos ...]` | Generate a new multi-repo workspace from Git worktrees |
| `ws edit` | Add/remove repositories in the current workspace (interactive) |
| `ws worktree <repo> <target> <branch>` | Create an isolated Git worktree |
| `ws clean` | Clean dependencies, caches, and build artifacts in the current workspace |
| `ws stop [--timeout S]` | Stop all running processes and services in the current workspace |
| `ws reset [--force] [--dry-run] [repos ...]` | Reset workspace repositories to their branch point or a clean HEAD |
| `ws delete [--force] [names ...]` | Delete workspaces and unregister associated worktrees |
| `ws build [dir]` | Build the current directory, auto-detecting Maven, Gradle, npm, Go, Cargo or Python |
| `ws deps [repos ...]` | Install workspace repository dependencies (Gradle, Maven, npm, uv, etc.) |
| `ws java [--json]` | Print the `JAVA_HOME`/`PATH` exports (or JSON) for the project's JDK via SDKMAN |
| `ws env-init [--force] [--check-only]` | Initialize or sync `config/.env` from `config/.env.example` |
| `ws env-load --envs E --services S --var NAME --values V` | Update a variable across per-environment `values.<env>.yaml` files |
| `ws benchmark [repos ...]` | Run unit test suites in parallel with a visual report |
| `ws run-local [--dir PATH] [--stop] [--start [REPOS]]` | Orchestrate and launch local microservices with live TUI |
| `ws kube [env\|logs\|shell]` | Kubernetes pod manager: env extraction, logs, shells (interactive without an action) |
| `ws hooks [install\|status\|uninstall\|run\|test]` | Git hooks and quality gate manager |
| `ws check` | Run the quality gate with condensed output (`--changed`, `--cache`, `--json`, `--skip`, `--budget`, `--dir`) |
| `ws changed [--json] [--dir DIR]` | Files changed vs. the base branch plus the working tree |
| `ws design` | Per-function design metrics and checks (`--changed`, `--files-from`, `--focus`, `--json`, `--verbose`, `--dir`) |
| `ws run` / `ws log` / `ws condense` | Condensed command output and saved full logs |
| `ws detect [--json] [--dir DIR]` | Detect repository technology stacks |
| `ws hook claude-worktree-create` | Run a coding-agent integration hook |
| `ws doctor` | Verify system tools, compilers, and development environment |
| `ws config init` | Initialize workspace configuration |

Every command from `ws generate` to `ws run-local` owns its options: `ws <command> --help`
prints them.

---

## 📖 Practical Guide & Common Workflows

### 1. Multi-Repo Workspaces & Git Worktrees

Enables working across multiple decoupled repositories grouped under an isolated development space, utilizing Git worktrees to prevent redundant filesystem clones.

```bash
# Create an isolated Git worktree for a specific branch
ws worktree /path/to/base-repo /path/to/target-worktree feature/new-api

# Create a workspace: new branch `checkout-v2` from main in api, from develop in web,
# and the existing branch release/1.4 in docs
ws generate checkout-v2 api web:develop docs@release/1.4

# Modify repositories linked in the current workspace (run from inside it)
ws edit

# From inside a workspace: drop build caches, preview a reset, install dependencies
ws clean
ws reset --dry-run api
ws deps api web

# Delete a workspace and unregister its worktrees without confirmation
ws delete --force checkout-v2

# Claude WorktreeCreate hook: suggest a confined central location (never creates files)
echo '{"root_path": "/src/api", "worktree_base": "fix-login"}' \
  | WORKSPACE_WORKTREES_DIR="$HOME/projects/worktree" ws hook claude-worktree-create
```

The Claude hook consumes the native JSON payload on stdin and is fail-open: malformed,
unsafe, or colliding inputs emit no suggestion and exit successfully. Suggested names are
sanitized and confined to `--base-dir` or `WORKSPACE_WORKTREES_DIR` (default
`~/projects/worktree`); the hook itself never creates or removes a worktree.

---

### 2. Local Microservices Orchestration (`ws run-local`)

Automatically discovers microservices in the workspace, allocates deterministic ports in the **8000–8999** range, rewrites inter-service endpoints (`wire_urls`), and launches an interactive TUI monitor.

It requires a workspace configuration (`ws config init`, see section 5); environments come
from its `environments` list. To rewire a URL such as `https://services-orders-staging-01.dev.my-domain.io`
to a local `orders` service, the hostname drops a `<namespace>-` prefix from `namespaces`
(default `core`, `services`, `tools`) and an `-<environment id>` suffix from the ids in
`environments` (default `dev`, `staging`, `prod`). Profiles are stored in `~/.config/run-local/profiles.json`, and
logs, PIDs and the last launch in `~/.local/share/run-local/`.

```bash
# Pick services, environments and profiles in the TUI (repos auto-detected from the cwd)
ws run-local --dir ~/projects/workspaces/checkout-v2/repositories

# Relaunch the last configuration without the TUI, optionally only some repos
ws run-local --start api,web

# Stop every service it launched
ws run-local --stop
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
| `workspace-commit-msg` | commit-msg | Conventional Commits subject, max 100 characters — only where the repo opts in |
| `workspace-gate` | pre-push | Protected-branch check, then 5 stages: secrets (gitleaks), commit policies, linters, design limits, test suites |

Before the stages, the gate refuses direct pushes to (and deletion of) protected branches:
`main`, `master`, `develop` and `staging` by default (`QG_PROTECTED` overrides the regex). The
commit-policy stage rejects empty messages and unapplied `fixup!`/`squash!`/`amend!` commits,
and warns on subjects over 100 characters.

Output is compact by default; a failing command keeps its full transcript at
`.git/workspace/quality-gate/latest.log` (`QG_OUTPUT=verbose` streams everything).
Skip stages with `QG_SKIP=gitleaks,commits,lint,design,tests` (`all` skips every stage), and
scope linters and tests to the pushed files with `QG_SCOPE=changed`.

Conventional Commits are **opt-in per repository**, so a global install never imposes a style
on projects with their own conventions: `git config workspace.commitStyle conventional` turns
on both the commit-msg check and the pre-push commit policy (`QG_COMMIT_STYLE=conventional`
does the same for one command).

Python tools come from the project's own environment: `ruff` and `pytest` resolve to the
repository's `.venv`, then `uv run` when there is a `uv.lock`, and only then to whatever is on
`PATH` (a global pytest lacks the project's dependencies; a global ruff may be another version).

The installed scripts are copies: after upgrading the package, run `ws hooks install [--global]`
again to refresh them.

Stage 4, **design limits**, always runs `ws design --files-from <files in this push>`
regardless of `QG_SCOPE` — it judges new code, so it is always scoped to what is actually
being pushed. If `ws` is not on `PATH` it warns and passes rather than blocking the push.

```bash
ws hooks install            # this repository (keys in .git/config, scripts in .git/workspace/hooks)
ws hooks install --global   # every repository (keys in ~/.gitconfig, scripts in ~/.config/workspace/hooks)
ws hooks status             # registration status per scope (also the default action)
ws hooks uninstall [--global]  # removes only the workspace-* hook sections
ws hooks run --scope changed --skip tests   # run the full gate script now (--timeout, --style, --output)
ws hooks test               # run the gate on the whole repository with a 120 s step timeout

ws check                    # run the gate now; condensed output, exit code preserved
ws check --changed --cache  # only changed files; skip if the tree is unchanged since the last pass
ws check --json             # versioned contract used by agent hooks
ws changed [--json]         # files changed vs. the base branch plus the working tree
```

Every `ws hooks` subcommand accepts `--dir` (default: the current directory). `ws check`
condenses the gate output to `--budget` characters (default 1500) and saves the full log on
failure (`ws log <id>`); `--skip` takes the same stage names as `QG_SKIP`.

### Design limits (`ws design`)

Measures every function's cyclomatic complexity, length (NLOC), parameter count and max
nesting depth via lizard — one deterministic engine
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
exclude = ["**/node_modules/**", "**/legacy/**"]   # replaces the default list
```

```bash
ws design                   # whole repo (git ls-files, or a walk without git)
ws design --changed         # only files changed vs. the base branch
ws design src/ pkg/foo.go   # specific files or directories
ws design --files-from list.txt  # newline-separated paths, relative to --dir (default: the current directory)
ws design --json            # versioned contract: {schema_version, status, violations, files}
ws design --changed --verbose  # also list every untouched pre-existing violation
```

**Legacy code must not get worse, new code must be clean.** With `--changed` or
`--files-from`, `ws design` compares each function against the merge-base with the default
branch (the fork point, not the tip of `main`). The base version is read with `git show` and
analysed in memory; functions match by file path, qualified name and parameter signature, so
Java overloads do not collide.

- A function that did not exist at the base (new, renamed, moved, or in a new file) is `new`
  and must meet the limits: it blocks.
- A legacy function never blocks, touched or not. A touched one is listed with the base value
  (`length 120 > 40 (was 118, +2)`), worsened ones first, so a regression is visible; an
  untouched one is folded into one line
  (`N pre-existing functions over the limits in touched files — see ws design --focus <path:line>`);
  `--verbose` lists them all.
- Line-based checks (hygiene, junk tests, layers) block on changed lines and only warn elsewhere.
- A full, unscoped scan has nothing to compare: everything is `legacy`, listed in full, exit `0`.
  It is an audit; the gate always runs with a scope.

Exit code is `1` only when something blocks in `block` mode, `0` otherwise (`off` prints
`design: off` and skips measuring). The text report has a "Blocking" section and a
"Pre-existing (not blocking)" section whose footer pushes toward a surgical fix: change only
that function, keep behavior, add a characterization test first, one function at a time. Each
line ends with a metric-specific hint (`complexity` → extract branches into named functions /
guard clauses, `length` → extract steps into well-named functions, `args` → introduce a
parameter object, `nesting` → return early, extract inner blocks). `--json` carries
`"origin": "new" | "legacy"`, `"blocking": bool` and `"base_value": int | null` (the value at
the base for a legacy function that existed there) per violation.

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
ws run --budget 4000 -- mvn test   # summary budget in characters (default 2500)
ws log <id> --grep ERROR    # read the saved full output (0600, 7 days / 200 logs)
ws log <id> --lines 120-180
ws log --last               # the most recent saved log
ws condense --command "pytest" --json < output.txt   # contract used by ai-governance hooks (--exit-code, --budget)
```

Logs are stored in `~/.local/state/workspace/logs/` (`WORKSPACE_LOG_DIR` overrides it).

The condenser is deterministic: tool profiles (pytest, jest/vitest, go, cargo,
maven/gradle, linters) keep the summary and every failure with context; ANSI codes,
progress bars, timestamps and repeated lines are removed; successful runs collapse to one
line; output never exceeds the character budget.

### Stack detection (`ws detect`)

`ws detect [--json] [--dir DIR]` reports stacks (java, kotlin, node, typescript, react, python, go, rust,
php, flutter, dotnet, docker, kubernetes, sql, migrations, github-actions, gitlab-ci, jenkins)
from marker files. ai-governance uses it to install only the rules a project needs.

### 4. Runtime, Build & Kubernetes Utilities

```bash
# Auto-detect the stack of the current directory and build (Maven, Gradle, npm, Go, Cargo, Python)
ws build

# Print the JAVA_HOME/PATH exports for the JDK the project needs (via SDKMAN)
eval "$(ws java)"
ws java --json

# Sync config/.env with config/.env.example (prompts only for missing values)
ws env-init
ws env-init --check-only

# Set LOG_LEVEL for api and web in values.dev.yaml and values.prod.yaml under --root
ws env-load --envs dev,prod --services api,web --var LOG_LEVEL --values debug,info \
  --root ~/projects/gitops/apps

# Run the unit tests of every workspace repository (or only the named ones) in parallel
ws benchmark api web

# Kubernetes: pod environment variable extraction (.env written with mode 600)
ws kube env

# Kubernetes: live pod log streaming and interactive shell
ws kube logs
ws kube shell
```

---

### 5. Workspace Configuration (`ws config`)

Bootstraps the `config.json` that `ws` reads for project naming, domain, namespaces and
environments. Written project-locally (`.workspace/config.json`) or user-globally
(`$XDG_CONFIG_HOME/workspace/config.json`, default `~/.config/workspace/config.json`), which is
the default scope. The first file found is used, in this order: `.workspace/config.json` of
the project root, `$XDG_CONFIG_HOME/workspace/config.json`, `~/.config/workspace/config.json`,
`config.json` at the project root.

```bash
# Interactively initialize project-local configuration
ws config init --local

# Non-interactive, user-global configuration
ws config init --global --yes --name my-project --domain my-domain.io

# Write to a custom path instead
ws config init --path ./custom-config.json --yes

# Overwrite an existing configuration without confirmation
ws config init --local --force --yes
```

`--name` defaults to the current directory name and `--domain` to `local.dev`; `--local`,
`--global` and `--path` are mutually exclusive.

The generated file has no `environments`; `ws run-local` then offers only `local`. Add one
entry per Kubernetes environment it should be able to read variables from:

```json
"environments": [
  {"id": "staging", "cluster": "dev", "namespace": "apps"}
]
```

`cluster` picks the kubectl context: `prod` uses the first context whose name contains
`prod`, `dev` the first one that does not. `namespace` is the namespace of the service pods.

---

## ⚙️ Configuration & Environment Variables

| Variable | Used by | Description | Default |
| --- | --- | --- | --- |
| `AI_REPOSITORIES_DIR` | `ws generate`, `ws edit` | Directory containing local project repositories used when wiring up a new/edited workspace. | none (falls back to values already present in the workspace's `.env`) |
| `WORKSPACE_WORKTREES_DIR` | `ws hook claude-worktree-create` | Confines suggested Git worktree destinations (`--base-dir` takes precedence). | `~/projects/worktree` |
| `WORKSPACE_LOG_DIR` | `ws run`, `ws log`, `ws check` | Where full outputs are saved. | `$XDG_STATE_HOME/workspace/logs` (`~/.local/state/workspace/logs`) |
| `WORKSPACE_AGENT` | all commands | Force agent (`1`) or human (`0`) output; otherwise detected from the agent environment. | auto |
| `XDG_CONFIG_HOME` | `ws config init`, config discovery, `ws hooks install --global` | Base directory for the user-global configuration and global hook scripts. | `~/.config` |
| `XDG_STATE_HOME` | `ws run`, `ws log` | Base directory of the log store. | `~/.local/state` |
| `JAVA_HOME` | `ws run-local` (process manager) | JDK home used when launching Java-based services locally. | whatever is already set; unset means the system default `java` |
| `QG_SCOPE` | pre-push gate | `all` or `changed`: scope of linters and tests. | `all` |
| `QG_SKIP` | all three hooks | Comma-separated stages to skip: `gitleaks`, `commits`, `lint`, `design`, `tests`, or `all`. | none |
| `QG_TIMEOUT` | pre-push gate | Timeout in seconds per step. | `900` |
| `QG_COMMIT_STYLE` | commit-msg hook, pre-push gate | `conventional` enforces Conventional Commits for one command (per repo: `git config workspace.commitStyle conventional`). | unset |
| `QG_PROTECTED` | pre-push gate | Regex of protected destination branches. | `^(main\|master\|develop\|staging)$` |
| `QG_OUTPUT` | pre-push gate | `errors` hides successful command output, `verbose` streams every command live. | `errors` |

`ws hooks run` sets the `QG_*` variables from its flags (`--scope`, `--skip`, `--timeout`,
`--style`, `--output`); `ws check` sets the scope from `--changed` and the skip list from `--skip`.
