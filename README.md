# ia-spec-ops-engine

A development framework for AI coding agents that is **agnostic to the agent**: a
catalog of engineering rules, a set of deterministic tools, and the glue that makes any
agent (Claude Code, Codex, Cursor, Aider, …) prefer those tools over reasoning — because
reasoning costs tokens and a tool costs none.

The repository is a source checkout with three independently installable Python
packages. It does not bootstrap, install, or configure anything by default.

| Package | Purpose | Installed only when explicitly requested |
| --- | --- | --- |
| `packages/ai-governance` | The framework: rules catalog, harness, context frugality, progress tracking, telemetry, Atlassian utilities | Yes |
| `packages/workspace` | Deterministic low-level tools (`ws`): Git worktrees, quality gates, local services, environment tools | Yes |
| `packages/spec` | Specification-driven workflows (MVP) | Yes |

Tell the coding agent which package and capability you want, e.g. "Use `ai-governance`
rules for Python and core practices in this repository" or "Install only the Workspace
Git-hook tooling." The agent must inspect the requested component and propose the exact
installation before making changes.

---

## 1. The idea in one sentence

What is deterministic runs as Python without an LLM (zero tokens, same result every
time). What is *behaviour* is written in a file the agent reads (`AGENTS.md`). What is
inherently tied to one host lives in a single, isolated adapter.

| Nature of the thing | Where it goes | Examples |
| --- | --- | --- |
| Runs every turn / would cost tokens if the LLM did it | Python code, no LLM | `frugal`, `progress`, `ws`, `telemetry`, `governance doctor` |
| Happens once / must adapt to each agent | Documentation the agent reads | harness wiring block, rule `00-deterministic-first` |
| Tied to one host by nature | One isolated adapter | `rules/core/hosts.py`, `ws hook claude-worktree-create` |

## 2. The three layers

```mermaid
flowchart TB
    subgraph GOV["packages/ai-governance — THE FRAMEWORK"]
        direction LR
        rules["rules/<br/>rules catalog + reversible<br/>injector into AGENTS.md"]
        harness["harness/<br/>tools index + self-wiring<br/>block + read-only doctor"]
        frugality["frugality/<br/>hooks that condense output<br/>and warn before waste"]
        session["session/<br/>`progress`: task state<br/>across sessions"]
        telemetry["telemetry/<br/>cost estimates, budget<br/>pacing, price feed"]
        tools["tools/<br/>`jira`, `confluence`<br/>as Markdown"]
        output["output.py<br/>agent output mode<br/>(compact, budgeted)"]
    end
    subgraph WS["packages/workspace — DETERMINISTIC TOOLS (`ws`)"]
        direction LR
        wt["worktrees"]
        hooks["git hooks +<br/>quality gate"]
        runlocal["run-local"]
        env["environment doctor,<br/>env/kube helpers"]
        cwh["integrations/claude/<br/>worktree_hook"]
    end
    subgraph SPEC["packages/spec — SDD (MVP)"]
        spec["spec new / plan / verify / finish"]
    end
    GOV -. "shared output convention,<br/>no imports" .- WS
```

`ai-governance` and `workspace` never import each other; each installs on its own.
They share a *convention* (the output contract in §8), not code.

## 3. One source of truth: `manifest.json`

```mermaid
mindmap
  root((manifest.json))
    rules — 29 Markdown rules
      0-harness
        how to behave: determinism first, announce, frugality
      1-core
        clean code, SOLID, DDD, testing, git, security, …
      2-stacks
        python, react, java, go, rust, kotlin, …
      3-infrastructure
        api, docker, k8s, ci/cd, migrations, …
      4-docs
        diagrams, ADRs
      each: id · category · file · description · triggers.globs
    tools — 15 deterministic tools
      each: id · package · command · purpose · trigger · io · replaces · fail_mode
      trigger
        before-shell-command
        after-shell-command
        on-turn-end
        on-worktree-create
        on-demand
```

Triggers use **agnostic names**. Nothing in the catalog mentions a specific agent. The
only file that knows "on Claude Code, `after-shell-command` lives in
`hooks.PostToolUse`" is `rules/core/hosts.py`, a lookup table. Another host is another
row, not more code.

## 4. Generating the harness (installation)

```mermaid
flowchart TD
    CMD["governance rules install --global --all<br/>governance harness install --global"]
    CMD --> CAT["RuleCatalog<br/>reads manifest.json"]
    CAT --> STO["RuleStorage<br/>copies the .md files to ~/.specops/rules/<br/>(sha256-tracked: your edits are never overwritten)"]
    CAT --> REN["AgentsRulesAdapter + harness/render<br/>render Markdown"]
    REN --> INJ["BlockInjector<br/>injects between markers, idempotent"]
    INJ --> MD

    subgraph MD["~/.config/agents/AGENTS.md"]
        direction TB
        own["(your own text, untouched)"]
        rb["&lt;!-- rules:start --&gt;<br/>table: rule | file | globs<br/>## Harness Tools<br/>table: tool | use for | command | trigger<br/>&lt;!-- rules:end --&gt;"]
        hb["&lt;!-- harness:start --&gt;<br/>## Harness Wiring<br/>automatic tools + host map + agent mode<br/>&lt;!-- harness:end --&gt;"]
        own --- rb --- hb
    end
```

`AGENTS.md` is a cross-agent standard. Running `install` twice never duplicates a block
(the injector replaces what sits between the markers). `uninstall` removes only the block
and keeps your text. Use `--local --root <dir>` for a project-scoped `AGENTS.md`.

**There is no installer that writes agent config.** The `harness` block tells the agent:
"if your runtime supports event X, register this command there (see the host map); if it
doesn't, run the command manually at that point". The agent self-configures by reading.
`governance doctor` then verifies — read-only — whether it did.

## 5. What happens on every agent turn (runtime)

```mermaid
sequenceDiagram
    participant A as Agent
    participant H as Host runtime
    participant PRE as frugal --pre-bash
    participant SH as Shell
    participant POST as frugal --post-bash
    participant TEL as telemetry thresholds --notify
    participant WT as ws hook claude-worktree-create

    A->>H: run a shell command
    H->>PRE: before-shell-command {command}
    Note over PRE: wasteful command? (lockfile cat, git log without -n, …)<br/>a tool that replaces it? (built from `replaces`)<br/>warns once per session · never blocks
    PRE-->>H: additionalContext: "Deterministic alternative: `ws worktree …`<br/>Announce it as ⚙ ws-worktree"
    H->>SH: execute
    SH-->>H: stdout (possibly huge)
    H->>POST: after-shell-command {command, stdout}
    Note over POST: tests → result + failing block only<br/>listings → head + tail · git diff/show → exempt<br/>full output saved to disk, cited as `full: &lt;path&gt;`
    POST-->>H: condensed stdout
    H-->>A: what the agent actually reads
    H->>TEL: on-turn-end
    Note over TEL: crossed 50 / 75 / 90 / 100 %<br/>of the daily or monthly budget?
    A->>H: create a worktree
    H->>WT: on-worktree-create {root_path, worktree_base}
    WT-->>H: ~/projects/worktree/&lt;repo&gt;-&lt;branch&gt;<br/>(fail-open: any error → host keeps its own path)
```

All of this is Python without an LLM: zero tokens, deterministic.

## 6. What the agent does on its own (rule `00-deterministic-first`)

Not a hook — text the agent reads in `AGENTS.md` and follows:

```mermaid
flowchart TD
    N["need: state, search, worktree,<br/>hooks status, Jira, test summary, …"]
    N --> Q{"is there a tool in the<br/>Harness Tools table?"}
    Q -->|yes| A1["announce in one line<br/>⚙ &lt;tool-id&gt; &lt;args&gt;"] --> U["run the tool<br/>(agent mode, compact output)"]
    Q -->|no| A2["⚙ none — doing it manually"] --> M["do it by hand,<br/>with the frugality practices"]
    U --> E{"was the compact<br/>output enough?"}
    E -->|yes| DONE["continue — never re-read<br/>what the tool condensed"]
    E -->|no| F["use the cited<br/>full: &lt;path&gt; / more: &lt;cmd&gt;"] --> DONE
    PRE["frugal --pre-bash reminds the agent<br/>of the tool if it forgot"] -.-> Q
```

Frugality practices the rule carries: `git diff --stat` before `git diff`, `jq` with the
minimal projection, `2>&1 | tail -40`, never print lockfiles, subagents with an explicit
output budget, save progress before `/compact` or `/clear`.

This is the only non-deterministic part of the system, and `frugal --pre-bash` backs it
up by reminding the agent of the tool when it forgets.

## 7. On-demand tools (the ones the agent chooses)

| Tool | What it does | Typical calls |
| --- | --- | --- |
| `progress` | Task state across sessions, keyed by ticket, spanning repos. Store: `~/.specops/progress/tasks/<id>.json` + `.md` log | `progress here` (resolves the task from cwd), `progress view T --json` (~300 tokens), `step` / `fact` / `link` / `note` / `close` / `reopen` |
| `ws` | Deterministic workspace operations | `ws worktree <repo> <target> <branch>`, `ws hooks install\|status`, `ws doctor`, `ws run-local`, `ws env-load`, `ws kube`, `ws config` |
| `jira` / `confluence` | Atlassian API rendered as clean Markdown — no MCP, no browser | `jira issue KEY`, `confluence read <page>` |
| `telemetry` | Local cost estimates and budget pacing | `telemetry usage --json`, `calibrate`, `prices update` (LiteLLM feed, cached), `ritmo` |

## 8. Agent output mode

```mermaid
flowchart TD
    Q{"is stdout a TTY?"}
    Q -->|yes| TTY["rich tables, colours, banners<br/>(for humans)"]
    Q -->|"no (pipe), or SPECOPS_AGENT=1"| AG["agent mode"]
    AG --> A1["plain text · no ANSI, no emoji<br/>one line per item"]
    AG --> A2["cap ~20 lines / 1500 chars<br/>last line: more: &lt;cmd&gt; --full"]
    AG --> A3["--json compact (no indent)"]
    AG --> A4["OK: / WARN: / INFO: to stdout<br/>ERROR: to stderr"]
```

When an agent runs a command, stdout is never a TTY, so agent mode kicks in by itself.
Tests measure each command's output size and fail if someone breaks the budget.

## 9. Verification: `governance doctor`

```mermaid
flowchart TD
    D["governance doctor --global"]
    D --> T["for each tool:<br/>binary on PATH?"]
    T -->|yes| T1[OK]
    T -->|no| T2[MISSING]
    D --> H{"host detected?<br/>~/.claude/settings.json"}
    H -->|no| H0["N/A host"]
    H -->|yes| H1["for each automatic trigger:<br/>command registered where hosts.py says?"]
    H1 -->|yes| H2[OK]
    H1 -->|no| H3[MISSING]
    H1 -->|invalid JSON| H4[WARN]
    D --> A["AGENTS.md:<br/>rules block? harness block?"]
    A -->|both| A1[OK]
    A -->|missing| A2[MISSING]
    D --> R["runtime dir writable?"]
    R -->|yes| R1[OK]
    R -->|no| R2[WARN]
    T1 & T2 & H0 & H2 & H3 & H4 & A1 & A2 & R1 & R2 --> S["summary: N ok, M missing, K warn<br/>exit 1 when anything is MISSING"]
```

It never writes. It replaces the "installer that verifies idempotency": the agent does
the writing by reading the block; a script does the verifying.

## 10. End-to-end lifecycle

```mermaid
flowchart LR
    C["1. clone<br/>uv sync --all-packages"]
    I["2. uv tool install -e<br/>packages/ai-governance<br/>packages/workspace"]
    R["3. governance rules install<br/>--global --all"]
    Hn["4. governance harness install<br/>--global"]
    W["5. the agent reads AGENTS.md<br/>and registers the hooks<br/>in its own config"]
    Dc["6. governance doctor --global<br/>exit 0 when wired"]
    Wk["7. normal work:<br/>hooks condense/warn · agent uses tools and announces ⚙<br/>progress keeps state · telemetry watches the budget"]
    C --> I --> R --> Hn --> W --> Dc --> Wk
    Wk -. "changed repo code → nothing to reinstall (editable)" .-> Wk
    Wk -. "changed rules/tools → re-run install (idempotent)" .-> R
```

---

## Development

This repo is a [uv](https://docs.astral.sh/uv/) workspace: all three packages share a
single `.venv` at the repository root.

```bash
uv sync --all-packages                 # shared .venv with the three packages + dev tools
uv run pytest                          # whole test suite
uv run ruff check && uv run ruff format --check packages/ tests/
uv run mypy
```

CI runs the same checks plus a wheel build and a hermetic smoke test of the installed
wheels (`tests/integration/verify_wheels.py`). The repo's own pre-push quality gate
(`ws hooks`) runs secrets scan, commit policy, lint and tests before every push.

To install a single package elsewhere (outside this workspace):

```bash
uv pip install -e packages/<pkg>   # packages/ai-governance, packages/workspace, packages/spec
```
