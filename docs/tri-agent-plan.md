# TriAgentTaskFlow (Plan · Build · Judge): Antigravity + Claude Code + Codex CLI

> **Origin and plan sign-off:** design consolidated on 2026-10-26 between the user, Antigravity, Claude Code and Codex.
> **Status:** **In execution.** Step 1 complete and installed (2026-10-26). Steps 2 to 4 designed (sections 6 to 8) and pending.
> **Content rule:** this document is generic. It does not name tickets, repos, people or products of any company; that data lives only in the local task registry and in the round log (section 8).
> **Base:** the engine (`ai-governance` + `ws`) **is already running and working well**. This plan builds on what already works and defines how to coordinate the three agents on **TriAgentTaskFlow**, the engine module that governs the lifecycle of each task.

---

## 0. Name

The flow and its engine module are called **TriAgentTaskFlow** (`ai-governance taskflow`). The name reflects what it does: it is not a passive list of steps, but the engine that **opens the task by itself, hands the baton between the three roles (Plan · Build · Judge) and demands evidence before closing**.

---

## 1. Context and operating premises

Three tools with active subscriptions and the engine (`ai-governance` + `ws`) running on the machine:

| Tool | Identifier in the engine | Plan | Models we will use | Installed version ✅ |
|---|---|---|---|---|
| **Antigravity** | `antigravity` | Business | **Gemini 4 Argon** (1M context, multimodal), **Gemini 3.8 Flash** (bounded tasks / `scout`) | 1.4.6 |
| **Claude Code** | `claude` | Max 5x | **Sonnet 5.5** (default), **Opus 5.5** / **Fable 5.1** (complex), **Haiku 5.5** (`scout` / `runner`) | 2.1.310 |
| **Codex CLI** | `codex` | Pro | **GPT-6.1 Sol** (judge / analysis), **GPT-6 Luna** (bounded tasks / `scout`) | 0.164.0 |

### Premises defined by the user

1. **We use `antigravity` for everything; we do not adopt `agy`.** Neither as a name in the documentation nor as an alias in the engine. The single identifier is `antigravity`.
2. **Antigravity has the largest quota of the three accounts.** That is why it absorbs all the heavy reading, multi-repo exploration, context analysis and planning.
3. **Astra is ruled out in Codex because it is too expensive.** In Codex we use **Sol** (`gpt-6.1-sol`, default model in `~/.codex/config.toml`) to judge and **Luna** (`gpt-6-luna`) for the lightweight work/subagents.
   - **Design consequence:** since Codex will not use Astra, the heavy architecture reasoning and deep unblocking fall on **Antigravity (Argon)** and the complex implementation on **Claude (Opus 5.5 / Fable 5.1)**. That way, when the work reaches Codex to be judged, it already arrives with a bounded scope, clear criteria, a concrete diff and deterministic evidence: a scenario where **Sol** performs at its best without spending on Astra.
4. **Monetary budget (750 USD) uninstalled and inactive (the code is not deleted).** ✅ Measuring or limiting spend in USD no longer matters. The `telemetry` code (`claude_usage.py`, `prices.py`, `schedule.py`, etc.) **is kept inactive in the repository**, but **is not installed**: the `claude-usage-budget.md` rule, the daily prices LaunchAgent and the `Stop` hook for spend alerts are left out of the installation. The only thing that matters operationally is the quota/window availability of each tool.

---

## 2. Roles: Separation of powers (`Plan · Build · Judge`)

The user defined three separate responsibilities: **one plans, another validates and codes, and a third judges**. No agent is both judge and party to its own code:

| AI | Role | Default model | For complex work / support |
|---|---|---|---|
| **Antigravity** | **Planner:** researches, reads long context, defines scope, acceptance criteria, plan and required verifications | Gemini 4 Argon | Argon (High mode); Flash 3.8 for `scout` and mechanical reads |
| **Claude Code** | **Validator and Implementer:** checks the plan against the repo, codes, runs the tests/checks and executes the close once approved | Sonnet 5.5 | Opus 5.5 / Fable 5.1 (hard implementation or bugs) |
| **Codex** | **Independent judge:** evaluates the delivered work against the plan and the executed evidence; approves or returns observations | GPT-6.1 Sol | GPT-6 Luna for `scout` / quick checks *(Astra is not used)* |

- **On small tasks:** the three roles are kept but with minimal deliverables (a plan of a few lines, a direct change and a quick judgment on the diff).

---

## 3. Task flow

| Phase | Owner | What it does and condition to advance |
|---|---|---|
| **0. Automatic opening** | Engine (TriAgentTaskFlow) | **Activates by itself** when a new task is picked up (by branch/ticket or session start), linking repo, branch and worktree with no manual intervention. |
| **1. Research and plan** | **Antigravity** (Argon) | Reads the necessary context, defines the goal, key files/lines (`path:L10-L50`), acceptance criteria, risks and verification commands. |
| **2. Validate the plan** | **Claude Code + Codex** (Sol) | Claude checks the plan's assumptions against the real code before editing and Codex validates it read-only. If both approve it, it advances to coding; if either sees a gap, it goes back to Antigravity with the observations (see rounds, section 8). |
| **3. Code and verify** | **Claude Code** | Implements the change, runs the tests and `ws check --changed`, and records in TriAgentTaskFlow the diff, the tests run and their results. |
| **4. Judge the work** | **Codex** (Sol) | Reviews that the diff meets the goal and the plan, and that the test evidence matches the current code. Rules: **Approved**, **Changes required** or **Evidence missing**. |
| **5. Fix (if applicable)** | **Claude → Codex** | Claude applies the corrections pointed out by the judge, re-runs verifications and Codex validates the adjustment. |
| **6. Close** | **Claude Code** | With Codex's favorable ruling and the quality gate green, pushes/opens the PR, updates the ticket and closes the task in TriAgentTaskFlow. |

### Operating rules

1. **TriAgentTaskFlow has to run by itself when a new task is picked up.** The developer should not have to remember to run manual initialization commands every time a ticket starts: upon detecting a new task or branch, the system must open or associate the record automatically, load the context at session start and update the state in each phase.
2. **Antigravity plans; Claude validates and implements; Codex judges.** If during implementation Claude fails twice on a complex bug, it records the hypotheses and the failure in TriAgentTaskFlow and leans on **Antigravity (Argon)** or **Codex (Sol)** for the diagnosis, keeping the editing of production code in Claude.
3. **Only one AI writes per branch.** Any parallel test or exploration goes in a separate worktree (`ws`).
4. **Disagreements are settled with evidence.** A reproducible test, a command result or the code's contract outweigh the opinion of any model. If it is a business or scope decision, the user decides.
5. **Clean context to implement.** Antigravity condenses the finding into exact references and concrete criteria inside TriAgentTaskFlow so that Claude goes straight to validating and coding without burning its window reading dozens of files.

---

## 4. Engine evolution: TriAgentTaskFlow + the best of `spec`

The engine (`ai-governance` + `ws`) **already works well** and TriAgentTaskFlow today solves:
- Persistence outside the chat (`~/.local/state/ai-governance/taskflow/tasks/<id>.json` and `.md`).
- Atomic writes and an exclusive per-file lock (`fcntl.flock`), avoiding corruption if two processes touch the same task.
- Automatic compaction (`summary` ≤ 500 chars, up to 8 active steps, automatic archiving of completed steps in the `.md` and a 400-char `digest` at Claude's session start).
- Multi-repo support (`repos` with `path`, `branch`, `pr`, `worktree`).

### What we add to the engine (without reviving `spec` as a separate tool)

`spec` kept its state in `.spec/` inside each individual repo, which clashes with multi-repo tasks and duplicates TriAgentTaskFlow. That is why we **work only with TriAgentTaskFlow** and add three key capabilities to it:

1. **Automatic start and linking on every new task (priority #1):**
   - If the agent starts on a branch with a ticket key (e.g. `ABC-123`) or receives a new ticket and the task does not exist in TriAgentTaskFlow, it is created and linked by itself to the current repo/worktree.
   - If an additional worktree is opened for the same task, it is associated automatically without losing the link to the main repo.
   - The three agents (`antigravity`, `claude`, `codex`) must receive the active state when their intervention starts, not just Claude.
2. **Phases rescued from `spec` (`Stage`):**
   - Incorporate the phase state in TriAgentTaskFlow aligned to the flow: `plan` (Antigravity) → `validate` / `work` (Claude) → `judge` (Codex) → `done` (Claude), recording which agent did each step (`--agent antigravity|claude|codex`).
3. **Evidence linked to the code, rescued from `spec` (`CheckResult` + tree fingerprint):**
   - Record which verifications were run (`ws check --changed`, targeted tests), their result (`PASS`/`FAIL`) and the code fingerprint (`HEAD` SHA + state of uncommitted files for each repo) at that moment.
   - Just like `finish()` did in `spec`, if someone modifies the code after verifying or after Codex's ruling, the evidence is marked as outdated (`stale`) and requires re-verifying before closing.

---

## 5. Agent instructions and configuration (`AGENTS.md`)

- **`GEMINI.md` no longer exists:** it was deprecated in our environment and `ai-governance doctor` already treats it as legacy to be removed. Antigravity loads its rules from `~/.gemini/config/rules/` (global), `.agents/rules/` (project) and `AGENTS.md`.
- **`AGENTS.md` + `.agents/rules/` as the single source in the repos:** Antigravity, Codex and Claude Code (≥ 2.1.277) all read `AGENTS.md` at the repository root.
- **`CLAUDE.md` (resolved 2026-10-26):**
  - In the repos, `installer.py` already migrates and deletes `CLAUDE.md` because its presence makes Claude Code ignore `AGENTS.md` by default.
  - In the global scope (`~/.claude/`) **the `~/.claude/CLAUDE.md` stub (`@AGENTS.md`) stays**: it is the only thing that makes Claude Code load `~/.claude/AGENTS.md`. Proof: with the stub, Claude follows an instruction that exists only in `~/.claude/AGENTS.md`; without the stub, it does not know it. `~/.claude/rules/*.md` does load by itself.
- **Subagents in Codex:** ✅ the installer (`CodexSpec` and `probe.py`) configures the `scout` subagent with **`"gpt-6-luna"`** (`GPT-6-Luna`; the short name `luna` is not a valid model) instead of `"terra"`, keeping **Sol** for the main agent and not using Astra in any profile.

---

## 6. How it fits with real work

> Designed by Antigravity (Argon), validated by Codex (Sol) in two rounds and reviewed by Claude (2026-10-26), based on a real task of the user. That task's data stays in the local registry, not here.

**Reference pattern (an example, not a requirement):** the flow must be able to support a case like this one. The subtask template, the repo types and the closing steps are configured per project; none is mandatory.

- **A parent ticket written by another person** (goal, decisions, split of work) and **subtasks that each person creates** with a fixed format: *Goal / What it includes / Context / How to connect the test environment*.
- **Mostly functional evidence:** end-to-end testing against a test deploy, published on the ticket as a *Step / Result / Screenshot* table + *Verified causes* + *Plan*; on the parent, one status line per subtask with links to PRs.
- **Several repos and several people:** service repos, a specs/RFCs repo, versioned contracts and dependencies on other people or teams.
- **Branches without the ticket key** in the name.
- **Close with its own steps:** remove temporary test commits, rebase onto the main branch, revert config touched in the test environment and go through human review.

### How TriAgentTaskFlow plugs in

1. **Parent task + subtasks.** The task is the parent ticket (it concentrates repos, decisions, dependencies and progress). **Each subtask goes separately through** `plan → validate → work → judge → staging → review → done` (plus `blocked`). The planner drafts the subtasks with the template; they are created in the ticket tracker only after a preview and the user's ok.
2. **Explicit link `(repo, branch, worktree) ↔ subtask`.** The current resolver looks for the key in the branch or a single active task per repo; with several subtasks in the same repo and branches without a key, that is not enough. It is set with `ai-governance taskflow bind --task <PARENT> --subtask <SUBTASK>`; if missing, the start hook asks once and persists it.
3. **Contract before code.** The planner (or a validator) marks `contract_change` with the affected contract; `work` is unblocked by recording `contract_ref` (commit/PR of the spec or RFC, or the contracts document version) approved by the user.
4. **Blockers with an owner.** `blocked {owner, needs, since}`: who unblocks it and what they need in order to respond.
5. **Two evidence cuts.** The code signature is `code_stamp = {head_sha, base_sha, tree_fingerprint}` (the `spec` fingerprint measures content, not commits: a rebase may not change it).
   - **Cut A — `staging`:** `ws check --changed` green + the judge's ruling on the tree with test commits → the user deploys and tests. The functional evidence is tied **immutably** to `(environment, deployed SHAs, table, causes, plan)` and is never carried over by itself to the final SHA.
   - **Cut B — `review` (after cleaning up and rebasing):** `ws check --changed` and a quick judgment on `git diff <deployed_sha>..<head_sha>` + closing checklist are always repeated. **Re-testing in the test environment:** the judge evaluates the impact of the diff and of the new base (dependencies, contracts, integrated behavior) and **the user decides**; with relevant impact or doubt, it is repeated.
6. **Permissions, invisibility and close.** Deploys and approvals are **always done by the user**. `review` = a clean PR ready for human review (with local drafts for the subtask's and the parent's comment); `done` requires the user to confirm **production** (`prod_shas`, date). Nothing from the engine or the agents appears in tickets, PRs, commits or team chats.

### Tests in the test environment (staging): done by a person

The functional test is run by **the user**: it requires real logins, product judgment and deploy approvals that are not delegated. The agents work around it:

- **Before (builder):** prepares the test script from the acceptance criteria: a *Step / Expected result* table ready to follow, plus what to look at if something fails (logs, endpoints, read-only commands).
- **During (user):** follows the script and notes the result and screenshots; the builder can read logs and state with read-only commands to find causes.
- **After (builder):** turns the notes into the *Step / Result / Screenshot* table + *Verified causes* + *Plan*, ties it to the deployed SHAs and prepares the draft of the ticket comment (published by the user or with their ok).
- **Judge:** checks that the evidence corresponds to the deployed SHAs and covers the acceptance criteria; it does not "re-test" the UI.
- **In the future (optional):** supervised browser automation for repetitive steps; it never replaces the human test nor touches approvals.

---

## 7. Configurable roles and agnostic engine

So that the engine can be shared, whoever configures it chooses **which agent fulfills each role**. Other people's AIs are added when needed, as one more adapter; the design does not depend on which ones they are.

### Configurability levels
- **Level 1 (Step 4):** fixed phase graph (`plan → validate → work → judge → staging → review → done`, plus `blocked`), **4 reassignable roles** (`planner`, `validator`, `builder`, `judge`) and **optional phases** that can be enabled per repo (e.g. no `staging` in repos without a deploy).
- **Level 2 (later):** arbitrary phases and transitions declared in config.

### Where the configuration lives
- **User — `~/.config/ai-governance/taskflow.toml`** (new file, in the config directory the engine already uses): roles → agent, model and headless command. Each person uses their own subscriptions.
- **Project — `.ai-governance/config.toml`** (exists; the schema is extended): repo policies (`gate`, `require_staging`, `contract_repos`, closing checklist), without fixing AI providers.

```toml
# ~/.config/ai-governance/taskflow.toml (proposed schema)
mode = "tri-agent"  # "tri-agent" | "dual-agent" | "single-agent"

[roles.planner]    # command tested on 2026-10-26
agent = "antigravity"
model = "gemini-4-argon-high"
exec = ["agy", "--model", "{model}", "--mode", "plan", "--print={prompt}"]

[roles.validator]  # two validators: the builder (before editing) and an independent read-only validator
agents = ["claude", "codex"]

[roles.builder]
agent = "claude"
model = "sonnet-5.5"
exec = ["claude", "-p", "--model", "{model}", "{prompt}"]

[roles.judge]      # command tested on 2026-10-26
agent = "codex"
model = "gpt-6.1-sol"
exec = ["codex", "exec", "-C", "{dir}", "-s", "read-only", "-m", "{model}", "-o", "{out_file}", "{prompt}"]

[adapters."<cli>"] # way to add another AI when needed (placeholder)
exec_readonly  = ["<cli>", "<read-only-flag>", "-m", "{model}", "{prompt}"]
exec_readwrite = ["<cli>", "-m", "{model}", "{prompt}"]
```

### Agnostic core vs adapters
- **Core (does not depend on any AI):** task and subtask state with atomic writes and lock (`fcntl.flock`), resolver and `bind`, phases, `code_stamp` and `stale`, evidence, `handoff` with a secrets filter, round log, drafts for the ticket tracker.
- **Per-agent adapter** (existing `AgentSpec` + new `RunnerAdapter`): where rules, skills, subagents and hooks are installed; how it is invoked headless; and **what level of isolation it guarantees**, declared and verified by `doctor`/`probe`:

| Adapter | Read-only | Brake on the second writer |
|---|---|---|
| `codex` | system sandbox (`-s read-only`): prevention | today it only has a `PostToolUse` hook: detection |
| `antigravity` | `--mode plan` + read-tool allow-list: **partial** prevention (any allowed `command(...)` that writes breaks it; e.g. `command(gh)`) | `PreToolUse` hook on `run_command` |
| `claude` | no sandbox of its own in `-p` | `PreToolUse` hook (today only `Bash`; add edit tools) |

- **Always-on detection:** comparing `tree_fingerprint` before and after each reader role does **not prevent** writes: it voids the step if the tree changed.
- **Reader roles:** `planner`, `judge` and `validator` when it is a **different** agent from the builder must run with an adapter that declares read-only by prevention; if it does not guarantee it, the config is rejected (or the user explicitly accepts detection only). If `validator` is the same agent as `builder`, it is a step of the same session before editing, not an isolated role.
- **Single writer (`writer_lease`):** on entering `work`, a lease `{subtask, agent, pid, host, worktree}` is taken per `(repo, branch, worktree)` with atomic creation under `flock`; a second writer is rejected; the lease is released when moving to `judge`/`blocked`, when the session closes or via CLI, and is only recovered if the owning process no longer exists on that host. Where the adapter has no pre-hook, the lease is detection, not prevention.

### Focused judges, path-based risk and tests first (Step 4)
Ideas taken from the "software factory" pattern (a repeatable, auditable pipeline of fixed code + agents + human checkpoints). They are **new** capabilities: today only `CheckResult` exists in `spec`.

**1. Focused judges.** Besides the general judge, `taskflow.toml` accepts a list of judges, each with a focus (`architecture`, `security`, `ux`…). They run in parallel, read-only and with clean context: the round package for their focus plus the diff and the evidence. None reads the others' rulings or resumes the builder's session.
- Each judge satisfies judge ≠ builder by effective identity. Switching model or session does not count as independence.
- Simple aggregation: the result is **Approved** only if all required judges approve. An error, a timeout or a required judge that does not exist does **not** count as approval. Observations go back to the builder all together, tagged with `[focus]` and not deduplicated (so as not to erase disagreements).
- Any change of `code_stamp` (code, base, contract, dependencies) re-runs **all** required judges. Re-judging only the affected foci is left for later.

```toml
# ~/.config/ai-governance/taskflow.toml
[[roles.judges]]
focus = "architecture"
agent = "codex"
required = true

[[roles.judges]]
focus = "security"
agent = "codex"
required = false   # becomes mandatory depending on risk
```
`[roles.judge]` (a single judge) still applies: if there is no `[[roles.judges]]`, that is the only required judge. If both exist, it is a config error.

**2. Path-based risk, without an AI deciding.** The engine classifies the change by crossing the touched files against patterns in `.ai-governance/config.toml`.
- Touched files = commits since `base_sha` **plus** uncommitted changes (staged, unstaged and new files), per repo, with both paths of each rename.
- The obligations of all matching rules **accumulate**: a change that touches security and UI requires both foci. Rules only **add** controls, never exempt from existing ones.
- The result is tied to the `code_stamp` and to the fingerprint of the risk config. Lowering the policy (removing rules or judges) requires human approval; if the builder touches it, the judge flags it as blocking.
- It does **not** enable auto-merge or deploy: merge and deploy approvals remain always human, at any risk level.
- Going back to staging: the impact evaluation with human decision (section 6) and the rebase rule (decision 5) are kept; a risk rule may **add** the requirement to re-test, never remove it.

```toml
# .ai-governance/config.toml (per project)
[[risk.rules]]
name = "datos-y-permisos"
paths = ["**/migrations/**", "**/auth/**", "**/permissions/**"]
required_judges = ["security", "architecture"]
restaging = true
```

**3. Tests first (optional, per project).** With `[tdd] mode = "optional" | "required"` (default `off`), the builder records the new test failing **before** the code and passing **after**, with the same command and the same test. The expected failure is stored as historical evidence, separate from the current gate (which requires everything green), and must be an assertion failure, not an execution or import error. The test is kept in the final code. It is not activated by risk in this first version.

### Invariants and operation with 1 or 2 AIs
- **No silent replacement:** if an agent fails (quota, invocation error), the phase stops and a notice is raised; the agent is never switched by itself.
- **Judge independence:** the **effective identity** (adapter binary/provider) is compared, not the role name: `judge` ≠ `builder`.
- **2 AIs (`dual-agent`):** A plans and builds, B judges read-only.
- **1 AI (`single-agent`):** a clean session of the same AI is **not independence**. The judge is `human`, or the user explicitly declares `unverified_same_agent_judge = true`, with date and consent recorded, visible in the state and in the close report.

### Validation decisions (Argon ↔ Codex ↔ Claude, 2026-10-26)
- Round 1 (Codex on Argon's v1): 7 blockers, all adopted in v2 (independent judge with 1 AI, configurability by levels, pilot with the current engine, evidence tied to deployed SHAs, user permissions and `review`≠`done`, explicit link to subtask, isolation and single writer).
- Round 2 (Codex on v2): 4 adjustments, resolved by Claude in this text: isolation declared per adapter for all reader roles; atomic lease with safe recovery and coverage per adapter; re-testing in staging decided by the user with impact evaluation; independence by effective identity and explicit consent.
- Round 4 (2026-10-27): Argon proposed focused judges, path-based risk and TDD; Codex approved with changes (full re-judging, real tree with uncommitted changes, protected risk config, accumulated obligations, TDD only optional, expected failure separate from the gate) and Claude incorporated them.
- Round 3 (user request, 2026-10-27): generic plan without company data, plan validation by Claude + Codex, rounds with shared context, round log outside git and staging tests done by a person.
- Claude's finding: Antigravity's allow-list includes `command(gh)` and `command(ws)`, which can write. User's decision: it is not restricted, because Antigravity is also used as a writing agent; in reader roles the restriction goes in the request (prompt) and the detection by tree fingerprint (section 7) remains in force.

---

## 8. Rounds between agents: shared context and log

> **Target design (Step 3).** Until it exists, in the pilot it is done by hand: the requester builds the package as a file, invokes the agent with the tested commands and saves the request and response in the log, updating `index.md`.

### Shared context between rounds
A "round" is an invocation of an agent with a request (plan, validate, judge) and its response. Between rounds the context is shared in two ways:

1. **Round package (always):** a file with the brief and only the background relevant to the role (previous outputs, the requester's notes); it is the only thing an agent that starts from scratch receives. It is what `handoff` does, with a secrets filter.
2. **Resumed session (optional, pending verification):** the same agent in the same role can continue its previous conversation instead of rereading everything: `codex exec resume <id>` and `agy --conversation <id>` (the options exist; how to capture each invocation's session id remains to be tested). It serves the planner ↔ validators back-and-forth.

**Rule:** the judge **never** resumes the builder's session nor receives its conversation; only the package (plan, diff, evidence). That way its judgment stays independent.

### Round log (outside git)
Each round is saved in the engine's local state, **never** inside the working repos nor in their history:

```
~/.local/state/ai-governance/taskflow/tasks/<tarea>/rounds/
  index.md                          # one line per round: n, date, phase, role, agent, model, ruling
  001-plan-planner-antigravity.md   # request + response + command used + session id
  002-validate-validator-codex.md
  ...
```

- It is queried with `ai-governance taskflow rounds <tarea>` (list) and `... rounds <tarea> <n>` (one round); in the future, a private HTML view to read it comfortably.
- `index.md` is what is read first: it shows at a glance how each decision was reached.

---

## 9. Execution roadmap

> Each step is executed when the user says so.

### Step 1 — Uninstall and leave inactive what is deprecated (750 USD budget and `CodexSpec` adjustment) — ✅ complete (2026-10-26, commit `d46d31a`)
- [x] Remove the budget rule: the installer no longer installs it and on reinstall removes its symlinks from `~/.gemini/config/rules/` and `~/.claude/rules/`.
- [x] Detach the `com.ai-governance.prices-update` LaunchAgent (`schedule.py`) from the installation: it is no longer installed or loaded, and the installer stops and deletes any plist left over from earlier versions.
- [x] Remove the global `Stop` hook for spend alerts (`telemetry thresholds --notify`) from `ClaudeSpec`; `_claude_stop` in `hooks.py` stays in the code, inactive. The project-level `stop-gate` `Stop` does not change.
- [x] **All the `telemetry` and prices code stays intact but inactive.** `schedule.unload()` also removes the legacy service that predates the LaunchAgent, so an old installation does not keep updating prices.
- [x] `CodexSpec` and `probe.py` configure `gpt-6-luna` instead of `terra` (README and `docs/getting-started.md` updated).
- [x] Verification: 609 `ai-governance` tests green and `ws check --changed` → `gate: passed`.
- [x] The `codex` user scope installs: block in `~/.codex/AGENTS.md` and `~/.codex/config.toml` (subagents on `gpt-6-luna`), `~/.codex/agents/scout.toml` and skills in `~/.agents/skills/`. Codex has no global per-file rules, so the packs' per-file rules do not reach it. Its hooks are only activated after `ai-governance probe --agent codex`.
- [x] Global `CLAUDE.md` test: the `@AGENTS.md` stub is needed (see section 5).

### Step 1b — Hygiene before the pilot — dropped (2026-10-27)
- Antigravity's allow-list stays as it is: it is also used as a writing agent. In a reader role, each request clarifies "read-only: do not modify files or run commands that change anything", and the tree fingerprint detects whether it wrote anyway.

### Step 2 — Operational pilot with the current engine (without touching code) — ✅ closed (2026-10-27)
- [x] Pilot on a real subtask (key only in the local registry). It went through plan → validate → work → judge (cut A) → verification of what was deployed → staging script → staging test done by the user (OK, no screenshots: the judge takes it as a statement) → judgment with real checks on the deployed SHA (Changes required: two failures of the fallback that normal use does not show). The fix and cut B are left to the branch's other owner.
- [x] Registry: 12 rounds in the local log, `[<subtask>][phase]` steps in the task registry and 18 frictions.
- **What the pilot confirmed:**
  - The judge is useful: it found a real bug that the checks did not cover.
  - With full permissions and the limit in the request, the planner reads the repo on its own and cites file:line; without permissions, the validator ended up planning.
  - A ruling goes stale within hours if another agent pushes to the same branch: `code_stamp` + `stale` is essential, not optional.
  - The source of truth for "which branch and which SHA" is neither the ticket nor the local checkout: it has to be verified at start (`git ls-remote`) and when judging.
- **Frictions that move to Step 3, in this order:**
  0. "Findings for another owner" exit: when the branch is worked by another person or agent, the judgment ends in a package with file:line and a proposal, instead of going back to work (friction 21).
  1. Automatic `stale` and re-verification of the current SHA before each judgment (frictions 15, 12).
  2. "Current integration branch + deployed SHA" as verified data in the round package, with `ls-remote` and not with local refs (2, 7, 8, 13).
  3. The judge runs the checks itself (tested: with full permissions it did so on a copy of the SHA) and records the judged `code_stamp`; the evidence is stored in the log, not in the session's temporary files (10, 11).
  4. Adapters: full permissions + limit in the request as the default mode of reader roles; output always to a file and a terminal-readable format (1, 3, 4, 17).
  5. Registry: `progress step` with the real syntax and `index.md` in a single place (6).
- **Outside the engine:** knowing which version runs in staging requires three different sources and the service does not expose its SHA (14); testing an error from a closed host requires a debug procedure, not a user step (18).

### Step 3 — Complete TriAgentTaskFlow engine (`ai-governance taskflow`; absorbs Step 4)

Plan approved after rounds 016–019 (Argon plans, Codex validates twice, Claude integrates). User decisions (2026-10-28), final:

- **D1 — `progress` ceases to exist.** No alias, no reading of the old format, no mentions. `taskflow` is the only tracking command, with or without AIs. The current data is moved once with a throwaway script that lives **outside this repo**.
- **D2 — Mandatory TDD.** It is only skipped if the human asks for it; who, why and their text are recorded.
- **D3 — Human approval is given in the chat** and the engine records it (action, target, `code_stamp`, the user's text); it expires if the code changes. Risky actions (deploy, production/canary, migrations/DB, infra, permissions, deletions, lowering the policy) require reinforced confirmation: the agent shows the consequence in plain language ("if it goes wrong, it may wipe the production database") and the user replies with a phrase that names the action and target; a generic "ok"/"dale" is not enough. The user's production window rules: never after 16:00, nor on Friday after 13:00.

#### Design
- **New modules** in `packages/ai-governance/src/ai_governance/taskflow/`: `models`, `store`, `resolver`, `config`, `stamp`, `lease`, `gates`, `risk`, `adapters`, `handoff`, `judge`, `draft`, `cli`. `compute_tree_fingerprint` is ported from `packages/spec` without depending on the package.
- **Single store** `~/.local/state/ai-governance/taskflow/tasks/<ID>/`:
  - `state.json`, `summary.md`, `friccion.md`, `evidence/`, `rounds/NNN-<fase>-<rol>-<agente>.md`, `rounds/index.md` (regenerated from `state.json`).
  - Writes under `flock`: reserves the round number, writes the round and updates the state; if a process dies midway, `index.md` is reconciled.
- **Lifecycle per subtask**, not just per task:
  - Each subtask has its own phase, `code_stamp`, TDD, evidence and approvals.
  - Phases: `plan → validate → work → judge → staging → review → done`, plus `blocked {owner, needs, since}` and the `findings` exit.
  - Backward transitions: judge rejection → `work` → re-judging; `blocked` → resume in the previous phase; expired evidence → the cut is repeated.
  - A `manual` task (no AIs) only uses steps, facts and notes, but cannot skip approvals or TDD if it declares code.
- **Multi-repo `code_stamp`:**
  - `base`, `head`, `index`, tree fingerprint (content, mode and symlink targets), submodules, risk policy fingerprint and dependency inputs (lockfiles).
  - Integration branch (`ls-remote`) and deployed SHA (with provenance) are kept separate. Without network it stays `unverified`, never "no changes".
- **Approvals (D3):**
  - `gate approve` stores task/subtask, action, target, consequence shown, the user's text and `code_stamp`.
  - **Traceability:** with Claude, the text is verified to appear in a real user message in the session transcript. With the other agents it is marked `declared`, and risky actions with `declared` do not advance.
  - **All entry points apply the same gates:** `status`, `close`, `round record` and `manual`. There are forgery and reuse tests.
- **Judges:**
  - Effective provider different from the builder, no silent fallback.
  - `single-agent` requires a human judge or a consented, visible exception.
  - All required foci (`[[roles.judges]]` plus those added by path-based risk) must give `pass` on the same `code_stamp`. A timeout, an error or a missing judge blocks.
  - They run in a `git worktree add --detach` of the judged SHA. The judge requires the work to be committed (it does not judge dirty changes). If the judge modifies the copy, it is kept and the path is reported; only intact copies are deleted.
- **Reader roles:** prevention where possible (Codex `-s read-only` in validation), detection in the rest (fingerprint before and after). If a reader modifies anything, the round is left `invalid` and a notice is raised with the paths; changes are never discarded.
- **Leases:** one writer per `(repo, branch)`. Recovery only if the PID is dead or the lease expired, never stealing it from a live process. Brake in `PreToolUse` of Claude (including the edit tools) and of Antigravity.
- **Path-based risk:** commits, staged, unstaged, untracked and both sides of renames. Obligations accumulate, and lowering the policy is a risky action.
- **Adapters** (flags verified with `--help`):
  - `antigravity` (executable `agy`): `--mode plan` to read, `accept-edits` to write;
  - `codex exec … -o` plus stdout/stderr saved separately;
  - `claude -p --dangerously-skip-permissions`.
  - All with a long timeout, output to the round and the limit written in the request.
- **Autonomous operation:**
  - `taskflow --help` documents prerequisites, phases, gates, failures, recovery and the exact next command. `status` always says what comes next.
  - The active state is injected at start in the three agents.
  - `handoff` filters secrets.
  - `draft` builds the comment for the ticket.

#### Deliverables (each with tests without real AIs: fake executables, temporary git repos, local bare remotes, injectable clock)
- [ ] **E1 — Store, base CLI and removal of `progress`:**
  - Store, resolver, `start/here/show/list/subtask/step/fact/note/decide/summary/status/close/rounds`.
  - `session/` and its tests are deleted, and the references are replaced in `cli.py`, `hooks.py`, `frugality/pre_check.py`, `install/{content,agents,installer}.py`, `tests/integration/verify_wheels.py`, `test_cli_dispatch.py`, `test_hooks.py`, `test_output_budget.py`, the READMEs, `docs/getting-started.md`, `AGENTS.md` and `.github/copilot-code-review-instructions.md`.
  - The installer deletes leftover `progress` skills.
- [ ] **E2 — Multi-repo `bind` and `stamp`,** with integration SHA and deployed SHA kept separate.
- [ ] **E3 — Per-subtask phases, mandatory TDD and D3 approvals** (traceability, reinforcement, window, expiry), with bypass, forgery and reuse tests.
- [ ] **E4 — Adapters, leases, `handoff` and context injection** in the three agents.
- [ ] **E5 — Path-based risk and judges in an isolated worktree** (independence, consolidation, timeouts).
- [ ] **E6 — `doctor`, `probe`, completion and docs;** end-to-end test guided only by `--help`.
- [ ] **Migration** (outside the repo, in the scratchpad):
  - `--dry-run` that shows the 14 tasks and the conflicts, and `--apply` that can be re-run without harm.
  - Keeps summaries, links, references, state and repos.
  - ONB-1477 becomes its own task with parent ONB-1410, with its 9 steps, 4 facts and 13 rounds, and the provenance noted.
  - The original stays intact until the user deletes it.
- **Done when:** suite green, `ws check --changed` → `gate: passed`, an agent with no context carries the CodeRabbit task from end to end with a three-line prompt, and its frictions come back to this plan.

### User decisions (2026-10-27)
1. Pilot: a real subtask already chosen (identified only in the local registry).
2. Claude and Codex validate the plan. This review (round 3) was validated by both; see the local log.
3. Other people's AIs are added when needed; they are not surveyed now.
4. The staging test is done by a person; the agents prepare the script, look for causes and build the evidence.
5. Rebase and staging: if resolving a conflict forced hand-touching the subtask's code, it is re-tested in staging; if the rebase went in clean or the conflict was in other files, `ws check` and judgment on the new SHA (cut B) is enough, without going back to staging.
6. Antigravity's allow-list is not restricted (Step 1b dropped); the read-only condition goes in the request.
7. Focused judges, path-based risk and optional tests first are added to Step 4 (not to the pilot), validated in rounds 014–015.
8. The pilot closes with the staging test declared OK by the user and the judgment on what was deployed; the fix is left to the branch owner and the frictions order Step 3.
