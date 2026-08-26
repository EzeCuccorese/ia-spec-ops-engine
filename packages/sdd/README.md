# cucco-sdd — AI Governance Engine & Spec-Driven Development (SDD)

> **Legacy reference:** this package is not used by Cucco v2. Do not treat the capability claims
> below as evidence of current v2 behavior. See [`next/`](../../next/).

Autonomous AI governance harness, FastMCP server, and multi-agent execution orchestrator for **Spec-Driven Development (SDD)**.

---

## 🚀 Strict 8-Phase Lifecycle

1. `sdd specify`: Phase 1 — Functional specification (`spec.md`).
2. `sdd clarify`: Phase 2 — Ambiguity resolution and risk audit (`clarify.md`).
3. `sdd plan`: Phase 3 — Technical blueprint and formal data contracts (`plan.md`).
4. `sdd checklist`: Phase 4 — Quality gates and Definition of Done (`checklist.md`).
5. `sdd tasks`: Phase 5 — Executable atomic tasks breakdown (`tasks.md`).
6. `sdd analyze`: Phase 6 — Static cross-artifact consistency audit and AST contract validation.
7. `sdd exec`: Phase 7 — Iterative task execution with Worker Agent and QA Reviewer Agent.
8. `sdd converge`: Phase 8 — Final acceptance criteria validation (Gherkin) and PR readiness.

*For accelerated bug fixes and minor patches, use `sdd quick`.*

---

## 🛡️ Core Features & Capabilities

- **Contracts First**: Formally define schemas (Zod, Java Records, Pydantic) before implementing logic.
- **Dynamic Context Budgeting (`sdd match-rules`)**: Ingests active diffs and injects only relevant scoped rules, saving 40% to 75% of context tokens.
- **AST Contract Auditor**: `sdd analyze` validates that DTOs and interfaces declared in `plan.md` exist in the AST of the source code.
- **Self-Healing Test Harness**: Multi-agent error parser for Pytest, JUnit, and NPM test traces with automated corrective re-prompting.
- **Native FastMCP Server (`sdd mcp`)**: JSON-RPC 2.0 Model Context Protocol server over `stdio` exposing tools (`sdd_verify`, `ws_clean`, `sdd_get_rules`, `sdd_feature_status`) and resources (`sdd://constitution`, `sdd://active-feature`) for Claude Code, Cursor, Antigravity, and VS Code.
- **Security Hooks**:
  - `sdd hook pre-tool`: Intercepts and blocks destructive commands (`rm -rf /`, piping `curl|sh`, unverified DB drops).
  - `sdd hook post-tool`: Instant verification (linters, test suites, secret scanning, post-mutation GET reads).
- **Multi-AI Adapters**: Automatic compilation for Claude Code, Cursor IDE (.mdc), Google Antigravity (AGY), GitHub Copilot, Windsurf, Gemini CLI, and ChatGPT.

---

## 🛠️ CLI Reference Table (`sdd`)

| Command | Description |
|---|---|
| `sdd mcp` | Launches the native Model Context Protocol (MCP) server over `stdio` |
| `sdd match-rules` | Dynamically filters rules by active files to optimize token budgets |
| `sdd init` | Initializes SDD workspace, detects stack, and deploys AI adapters |
| `sdd feature <name>` | Sets or inspects the active feature with worktree isolation |
| `sdd specify` / `sdd plan` | Assists in authoring lifecycle phase specifications |
| `sdd verify` | Runs automated quality gate (linters, tests, secrets, confirmation reads) |
| `sdd analyze` | Performs cross-artifact consistency audit and AST contract validation |
| `sdd harness run` | Orchestrates multi-agent execution with Worker and QA Reviewer |
| `sdd gate` | Captures quality gate baselines and detects test/coverage regressions |
| `sdd hook` | Executes pre-tool and post-tool security/verification hooks |
| `sdd finish` | Finalizes feature cycle, pushes branch, creates PR, and cleans worktree |
| `sdd sync` | Reinstalls CLI and synchronizes project AI adapters across worktrees |
| `sdd quick <desc>` | Fast-path atomic workflow for bug fixes and patches |
| `sdd audit [--deep]` | Comprehensive codebase debt audit cataloged in `.specify/tech-debt.md` |
| `sdd revoke` | Revokes and cleans SDD configurations with automatic backup |
