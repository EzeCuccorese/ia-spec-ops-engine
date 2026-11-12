# ia-spec-ops-engine workspace — Deterministic Quality Gates & Agent Execution Engine

**Workspace Engine (`ws`)** provides deterministic, non-interactive CLI primitives for AI coding agents and Git hooks: multi-stack pre-push Quality Gates, per-function design and hygiene checks, repository stack detection, and condensed command execution.

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

### 2. Environment Diagnostics (`ws doctor`)
Inspect system compilers, tools, and runtimes:
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
│   │   └── manage_hooks.py    # `ws hooks`
│   ├── condense/              # `ws run` / `ws condense` / `ws log`: deterministic condenser and private log store
│   ├── design/                # `ws design`: lizard metrics, hygiene, junk-test and layer checks, merge-base ratchet
│   ├── config/                # `ws config show` — effective workspace settings and origin inspection
│   ├── services/              # Stack detection, change sets, Git hooks/quality gate, monorepo test planning
│   ├── common/                # Safe subprocess, ANSI colors and agent-mode output
│   └── resources/
│       └── hooks/             # Git hook scripts: pre-commit, commit-msg, pre-push (quality gate)
└── tests/                     # Unit and acceptance tests
```

---

## 📋 Subcommand Reference

| Command | Purpose |
| --- | --- |
| `ws hooks [install\|status\|uninstall\|run\|skip\|gate-config\|test]` | Git hooks and quality gate manager |
| `ws check` | Run the quality gate with condensed output (`--changed`, `--cache`, `--json`, `--skip`, `--budget`, `--dir`) |
| `ws changed [--json] [--dir DIR]` | Files changed vs. the base branch plus the working tree |
| `ws design` | Per-function design metrics and checks (`--changed`, `--files-from`, `--focus`, `--stats`, `--suggest`, `--json`, `--verbose`, `--dir`) |
| `ws run` / `ws log` / `ws condense` | Condensed command output and saved full logs |
| `ws detect [--json] [--dir DIR]` | Detect repository technology stacks |
| `ws config show [--origin] [--json]` | Inspect effective workspace configuration and where each value came from |
| `ws doctor` | Verify system tools, compilers, and development environment |

---

## 📖 Practical Guide & Common Workflows

### 1. Git Hooks & Multi-Stack Quality Gate (`ws hooks`, `ws check`)

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
Repos whose CI already runs the full suite can skip a stage by default: `ws hooks skip set tests`
(also `show` and `clear`). It is stored in the repo's shared git config, so every worktree of the
repo inherits it, and only the `pre-push` gate reads it. `QG_SKIP` in the environment overrides it.

Skip stages with `QG_SKIP=gitleaks,commits,lint,design,tests` (`all` skips every stage), and
scope linters and tests to the pushed files with `QG_SCOPE=changed`.

Conventional Commits are **opt-in per repository**, so a global install never imposes a style
on projects with their own conventions: `git config workspace.commitStyle conventional` turns
on both the commit-msg check and the pre-push commit policy (`QG_COMMIT_STYLE=conventional`
does the same for one command).

Each stack runs with the project's own tools, never a global one that cannot work:

- **Python:** `ruff` and `pytest` resolve to the repository's `.venv` (or `venv`), then
  `uv run` when there is a `uv.lock`, then the env Poetry, Pipenv or PDM keeps outside the repo,
  and only then to whatever is on `PATH`. A project with `poetry.lock`, `Pipfile.lock` or
  `pdm.lock` but no env in this checkout (a new worktree) fails with the install command instead
  of running a global pytest. A `No module named ...` failure is reported as an environment
  problem, with the install command, not as a failing test.
  Without the env, ruff runs the version the lockfile pins (`uv tool run ruff@<version>`).
- **JS/TS:** scripts run with the package manager of the lockfile (`pnpm`, `yarn`, `bun`, else
  `npm`). The Node pinned in `.nvmrc` / `.node-version` is taken from nvm when installed (a
  warning otherwise). Dependencies declared but no `node_modules` fails with the install command.
- **PHP:** dependencies declared but no `vendor/` fails with `composer install`.
- **JVM / Flutter:** `./mvnw` wins over `mvn`; the SDK pinned with FVM wins over the global one.

Hooks launched from an IDE or a desktop Git client lack the login shell's `PATH`, so the gate
appends the usual per-user tool directories (`~/.local/bin`, Homebrew, nvm's default Node,
sdkman, cargo, go, fvm); the push's own `PATH` still wins.

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
ws check --changed --cache  # only changed files; skip if the tree is unchanged since the last pass for that scope+skip
ws check --json             # versioned contract used by agent hooks
ws changed [--json]         # files changed vs. the base branch plus the working tree
```

Every `ws hooks` subcommand accepts `--dir` (default: the current directory). `ws check`
condenses the gate output to `--budget` characters (default 1500) and saves the full log on
failure (`ws log <id>`); `--skip` takes the same stage names as `QG_SKIP`.

### 2. Design limits (`ws design`)

Measures every function's cyclomatic complexity, length (NLOC), parameter count and max
nesting depth via lizard — one deterministic engine
covering Java, JavaScript/TypeScript/TSX/JSX, Python, Go, Kotlin, C#, PHP, Rust, Swift,
Scala, Ruby, C/C++ and more (priority for tests and docs here: Java, JS/TS, Python, Go,
then the rest). **Dart is not supported by lizard**, so `.dart` files are skipped.
Python's `self`/`cls` are not counted as parameters.

Defaults: `mode = "block"`, `max_complexity = 10`, `max_function_lines = 40`,
`max_args = 4`, `max_nesting = 3`. Vendored/generated paths are excluded by default
(`node_modules`, `vendor`, `dist`, `build`, `target`, `.venv`, `generated`, `*.min.js`).

Configure the optional `[design]` table in `<root>/.workspace/config.toml` (or user global
`~/.config/workspace/config.toml` or personal `~/.config/workspace/repos/<repo-name>.toml`) —
`ws design` never reads or writes the repository's
own linter configs (eslint, checkstyle, ruff, golangci-lint, ...) to decide its limits:

```toml
[design]
mode = "warn"           # block | warn | off
max_complexity = 12
max_function_lines = 60
max_args = 5
max_nesting = 4
exclude = ["**/legacy/**"]                         # added to the default list (additive across defaults, user, and repo)
```

```bash
ws design                   # whole repo (git ls-files, or a walk without git)
ws design --changed         # only files changed vs. the base branch
ws design src/ pkg/foo.go   # specific files or directories
ws design --files-from list.txt  # newline-separated paths, relative to --dir (default: the current directory)
ws design --stats            # metric distribution (p50/p90/p99/max) per language and prod vs test
ws design --suggest          # propose [design] limits from prod p99, ready to paste (implies --stats)
ws design --stats --json     # structured stats object; adds "suggested" block with --suggest
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

```bash
ws design --focus src/app/orders.py:142   # focused brief for the function at that line:
                                           # range, all four metrics vs. limits, pass/fail,
                                           # hints for the failing ones, numbered source
                                           # (capped at 120 lines). Exit 1 if it violates.
```

**Hygiene checks.** Alongside the four function metrics, `ws design` runs three
deterministic, line-based checks enforcing rule 01 ("never swallow exceptions") and
rule 11 ("self-documenting code") from the ai-governance catalog:

- `empty-catch` — a `catch`/`except`/error-check block whose body is empty or holds only
  comments: `catch (...) { }` (Java, Kotlin, JS/TS/TSX/JSX/MJS/CJS, C#, PHP, Dart, Swift,
  Scala), Python `except ...: pass`/`...` (via `ast`), Go `if err != nil { }`, Rust
  `Err(_) => {}` / `Err(_) => ()`.
- `todo-ticket` — a comment with uppercase `TODO`/`FIXME`/`XXX` and no ticket reference (a
  `PROJ-123`-style key, `#123`, or a URL). String literals and identifiers are ignored.
- `commented-code` — a run of 2+ consecutive full-line comments that look like code.

**Junk-test checks.** Five more deterministic checks enforce the ai-governance testing
rule ("a test must assert observable behavior"): `test-no-assert`, `test-trivial-assert`,
`test-mock-only`, `test-sleep`, and `test-duplicate`.

**Layer boundaries (`architecture` profile).** With the `architecture`
profile enabled (top-level `profiles = ["architecture"]` in `.workspace/config.toml` or personal repo config),
`ws design` also checks that inner layers never import outer ones.

### 3. Condensed command output for agents (`ws run`, `ws log`, `ws condense`)

```bash
ws run -- mvn test          # runs, keeps the exit code, prints a condensed summary
ws run --budget 4000 -- mvn test   # summary budget in characters (default 2500)
ws log <id> --grep ERROR    # read the saved full output (0600, 7 days / 200 logs)
ws log <id> --lines 120-180
ws log --last               # the most recent saved log
ws condense --command "pytest" --json < output.txt   # contract used by ai-governance hooks (--exit-code, --budget)
```

Logs are stored in `~/.local/state/workspace/logs/` (`WORKSPACE_LOG_DIR` overrides it).

### 4. Stack detection (`ws detect`)

`ws detect [--json] [--dir DIR]` reports stacks (java, kotlin, node, typescript, react, python, go, rust,
php, flutter, dotnet, docker, kubernetes, sql, migrations, github-actions, gitlab-ci, jenkins)
from marker files. ai-governance uses it to install only the rules a project needs.

---

## ⚙️ Configuration & Environment Variables

### Configuration layers

Settings resolve across three configuration layers (lowest to highest priority):
1. **user global**: `~/.config/workspace/config.toml` (XDG)
2. **in-repo**: `<repo>/.workspace/config.toml`
3. **personal per-repo (outside working tree)**: `~/.config/workspace/repos/<repo-name>.toml` (stable across git worktrees of the same repo, derived from the main checkout directory name)

Full setting precedence: **default < user file < repo file < personal repo file < git config < environment variable < CLI flag**.
`ws config show [--origin] [--json]` prints which configuration files were found, the effective values and where each came from.
The `[design]` table and `profiles` live in the same unified configuration files, and `exclude` is additive across all layers.
Config, state and data directories follow XDG and accept `WORKSPACE_CONFIG_DIR` /
`WORKSPACE_STATE_DIR` / `WORKSPACE_DATA_DIR`.

Gate settings sit in the `[gate]` table. Priority for them is
**env `QG_*` > `git config workspace.*` > personal repo file > repo file > user file > default**, so
`git config workspace.skip tests` and `QG_SKIP=tests` keep working. `git config` keys:
`workspace.skip`, `workspace.commitStyle`, `workspace.protected`, `workspace.timeout`.
The pre-push, pre-commit and commit-msg hooks call `ws hooks gate-config`, which prints an
assignment only for settings the config files decide. `ws hooks status` warns when this repo
has gate settings (git config or `.workspace/config.toml`) but the gate is not installed.

| Key | Env var | Default | Meaning |
|---|---|---|---|
| `gate.skip` | `QG_SKIP` | `[]` | Gate checks to skip: gitleaks,commits,lint,design,tests,all |
| `gate.scope` | `QG_SCOPE` | `all` | Scope of linters and tests: all, changed |
| `gate.output` | `QG_OUTPUT` | `errors` | Gate output detail level: errors, verbose |
| `gate.protected_branches` | `QG_PROTECTED` | `^(main\|master\|develop\|staging)$` | Regex of branches the gate refuses to push to directly |
| `gate.timeout_seconds` | `QG_TIMEOUT` | `900` | Timeout of each gate step |
| `gate.commit_style` | `QG_COMMIT_STYLE` | `""` | Set to `conventional` to enforce it |
| `logs.retention_days` | `WORKSPACE_LOG_RETENTION_DAYS` | `7` | Age after which `ws log` entries are pruned |
| `logs.max_entries` | `WORKSPACE_LOG_MAX_ENTRIES` | `200` | Most `ws log` entries kept |
| `output.max_lines` | `WORKSPACE_OUTPUT_MAX_LINES` | `20` | Agent-mode output: lines before truncating |
| `output.max_chars` | `WORKSPACE_OUTPUT_MAX_CHARS` | `1500` | Agent-mode output: characters before truncating |
