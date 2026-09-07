# Universal AI Coding Agents Guide for SpecOps Engine

Welcome to **SpecOps Engine**. This guide is written specifically for AI coding agents (Google Antigravity, Anthropic Claude Code, Cursor, Codeium Windsurf, Aider, Codex, and custom LLM runtimes) operating autonomously or semi-autonomously in this repository.

---

## ⚡ 1. Post-Clone Bootstrap Protocol

Whenever an agent clones this repository into a new workspace, execute the following 4-step sequence before reading or changing domain code:

```bash
# Step 1: Install the monorepo in editable mode with development tools
uv pip install -e ".[dev]"
# Or if uv is not available:
pip install -e ".[dev]"

# Step 2: Initialize project-local or global configuration
specops config init --local --yes
# Or directly via repo binary:
./bin/specops config init --local --yes

# Step 3: Install the governance adapter for your specific AI platform
specops agent install <your-agent>
# Examples:
#   specops agent install antigravity  (Configures AGENTS.md)
#   specops agent install claude       (Configures CLAUDE.md)
#   specops agent install cursor       (Configures .cursorrules)
#   specops agent install windsurf     (Configures .windsurfrules)
#   specops agent install aider        (Configures .aider.conf.yml)
#   specops agent install all          (Configures all supported agents)

# Step 4: Verify system diagnostics and spec compliance
specops doctor && specops audit
# Or via repo binaries:
./bin/specops doctor && ./bin/specops audit
```

---

## 🧭 2. Multi-Agent Adapter Matrix

SpecOps is **100% agent-agnostic**. It does not enforce a proprietary agent runtime or hardcode platform expectations. Every adapter injects a non-destructive reference to `.spec/governance.md`:

| Agent / Runtime | Identifier | Target File | Adapter Behavior |
|---|---|---|---|
| **Google Antigravity** | `antigravity` | `AGENTS.md` | Reversibly injects `<!-- spec:governance -->` marker linking `.spec/governance.md`. |
| **Universal Codex** | `codex` | `AGENTS.md` | Universal Markdown governance standard. |
| **Anthropic Claude Code** | `claude` | `CLAUDE.md` | Native Claude guidelines file; integrates with `.claude/` tools and `AskFollowupQuestion`. |
| **Cursor IDE** | `cursor` | `.cursorrules` | Injects root rules; also supports native `.cursor/rules/*.mdc` standards. |
| **Codeium Windsurf** | `windsurf` | `.windsurfrules` | Injects workspace instructions. |
| **Aider AI** | `aider` | `.aider.conf.yml` | Injects `read: [.spec/governance.md]` so Aider always retains governance in context. |
| **GitHub Copilot** | `copilot` | `.github/copilot-instructions.md` | Injects instructions for GitHub Copilot Workspace and VS Code. |
| **Google Gemini CLI** | `gemini` | `GEMINI.md` | Native instruction file for Google Gemini CLI and Code Assist. |
| **Custom Agent** | `custom` | Custom `--file` | Allows passing any path, e.g. `specops agent install custom --file INSTRUCTIONS.md`. |

To uninstall or clean any adapter:
```bash
specops agent uninstall <agent> --apply
```

---

## 🏛️ 3. Architecture & Binary Ecosystem

The monorepo contains 3 decoupled packages, all accessible through unified wrappers in `./bin/`:

```
cucco-specops-engine/
├── bin/
│   ├── specops        # Master orchestration CLI
│   ├── spec           # Spec-Driven Development (SDD) CLI
│   └── ws             # Workspace DevOps & Worktree CLI
├── packages/
│   ├── ai-governance/ # Standards catalog (28 rules), frugality, telemetry, session tracking
│   ├── spec/          # Honest SDD workflow, AST mutation testing, judge, audit
│   └── workspace/     # Git worktrees, microservices orchestrator, quality gates
├── .spec/             # Governance state, policies, verification, and active specs
└── .specops/          # Workspace project configuration (config.json, rules)
```

### CLI Command Summary

- **`specops`** / **`governance`**:
  - `specops config init`: Generate `.specops/config.json` or `~/.config/specops/config.json`.
  - `specops agent install <name>`: Install AI governance adapters.
  - `specops doctor`: Unified environment and runtime diagnostics.
  - `specops audit`: Validate repository hygiene against governance checkpoints C1–C6.
  - `specops rules [install|uninstall|list]`: Reversibly install software engineering standards.
  - `specops frugal`: Condense verbose command/test outputs.
  - `specops statusline`: Real-time token spend and pacing status.
  - `specops progress` (`progreso`): Lightweight task tracking across sessions.
  - `specops jira` / `specops confluence`: Zero-MCP Markdown Atlassian integration.

- **`spec`**:
  - `spec init`: Initialize repository governance.
  - `spec preflight <name> [--worktree]`: Baseline check and worktree provisioning.
  - `spec new <name>`: Create new specification.
  - `spec plan`: Create architecture plan.
  - `spec tasks`: Break plan down into tasks.
  - `spec work`: Transition to implementation mode.
  - `spec test-assist --next`: Return the next uncovered Gherkin scenario.
  - `spec mutate <target>`: Run AST mutation analysis to detect missing assertions.
  - `spec verify`: Run deterministic test checks from `.spec/verification.json`.
  - `spec judge`: Evaluate craftsmanship and code bloat.
  - `spec finish`: Seal completed specification upon passing verification.

- **`ws`**:
  - `ws generate <name> [repos...]`: Multi-repo workspace provisioner.
  - `ws worktree <repo> <target> <branch>`: Isolated Git worktree manager.
  - `ws run-local`: Launch local microservices with terminal dashboard.
  - `ws hooks [install|run]`: 5-stage pre-push Quality Gate.
  - `ws kube [env|logs|shell]`: Kubernetes environment manager.
  - `ws doctor`: Diagnostics for runtimes (Java, Node, Docker, uv, Git).

---

## 🔄 4. Spec-Driven Development (SDD) Lifecycle

Agents modifying or adding features MUST strictly follow the honest SDD cycle:

```
                  ┌──────────────┐
                  │ spec preflight
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │   spec new   │ ◄── Requirements Interview (Ask user via modal)
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │  spec plan   │ ◄── Architectural Plan & Gherkin Scenarios (@s1, @s2...)
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │  spec tasks  │ ◄── Detailed Task Breakdown
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │  spec work   │ ◄── TDD Loop: spec test-assist --next & spec mutate
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │ spec verify  │ ◄── Deterministic Verification & Evidence
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │  spec judge  │ ◄── Prune Code Bloat & Verify Traceability
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │ spec finish  │ ◄── Explicit User Sign-Off
                  └──────────────┘
```

### Craftsmanship Disciplines (Uncle Bob TDD)
1. **First Law**: Do not write production code unless it is to pass a failing unit test.
2. **Second Law**: Do not write more of a unit test than is sufficient to fail (compilation/import errors count as failure).
3. **Third Law**: Do not write more production code than is sufficient to pass the one failing unit test.

### Scenario Traceability (`@s` tags)
- Acceptance criteria in `.spec/specs/<slug>/spec.md` must be tagged with `@s1`, `@s2`, etc.
- Every scenario must map to at least one test.
- `spec verify` audits traceability, and `spec finish` will reject completion if scenarios remain uncovered.

---

## 🔒 5. Safety Invariants

1. **Immutable Evidence**: Never edit files inside `.spec/evidence/` directly. They are recorded cryptographically by `spec verify`.
2. **Never Edit State by Hand**: Do not manually modify `.spec/state.json` or `.spec/ownership.json`. Always use the `spec` CLI or internal `SafeWriter`.
3. **Zero AI Mentions in Git**: Do NOT add AI attribution, robot emojis (🤖), or mentions of LLMs/agents in Git commit messages or PR descriptions.
4. **Scope Isolation**: Never edit files outside the agreed active specification or task scope without explicit confirmation from the human engineer.
