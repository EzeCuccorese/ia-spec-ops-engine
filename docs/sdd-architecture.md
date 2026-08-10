# SDD Architecture & Multi-AI Adapters

The **Spec-Driven Development (SDD)** engine in the toolkit operates on standardized Markdown artifacts and state files inside `.specify/`:

- **`.specify/feature.json`**: Active feature tracking state (`active_feature`, `current_phase`, timestamps).
- **`.specify/constitution/`**: Project principles, architectural rules, and tech stack standards (`index.md`, `mission.md`, `tech-stack.md`, `architecture.md`).
- **`.specify/specs/<feature-name>/`**: 8-stage SDD lifecycle artifacts:
  - `spec.md`: Functional specification with user stories and Gherkin scenarios.
  - `clarify.md`: Ambiguity resolution & quality gate analysis.
  - `plan.md`: Technical blueprint with Mermaid sequence diagrams & formal contracts (Zod/DTOs).
  - `checklist.md`: Quality Gates, Definition of Done (DoD), and post-mutation GET confirmation reads.
  - `tasks.md`: Executable task breakdown ordered strictly across 4 SDD pillars.
- **`.specify/memory.md`**: Cumulative historical memory of architectural decisions.
- **`.specify/history/`**: Persistent execution logs for Worker, QA Reviewer, and Leader agents (`<timestamp>-<task_id>-<role>.md`).
- **`.specify/tech-debt.md`**: Inventory of identified technical debt.

---

## Step-by-Step Lifecycle & Execution Harness

Feature development progresses sequentially, requiring explicit human review & sign-off at each checkpoint:

```
sdd specify  -->  sdd clarify  -->  sdd plan  -->  sdd checklist  -->  sdd tasks  -->  sdd analyze  -->  sdd exec (harness)  -->  sdd converge
```

During Phase 7 (`sdd exec`), the **Multi-Agent Execution Harness (`sdd harness`)** manages task orchestration:
1. **Context Window Optimization**: Extracts minimal task payloads to prevent context bloat.
2. **Multi-Agent Roles**: Leader dispatches tasks to Worker (implementer) and QA Reviewer (validator).
3. **Auto-Correction Loop**: Auto-remediates QA failures up to 3 retries.
4. **Persistent History**: Records structured task execution logs in `.specify/history/` to eliminate context loss.

For bug fixes and minor patches, `sdd quick` provides an accelerated, strictly scoped path.


---

## Dynamic End-to-End AI Agent Adaptation Matrix

The toolkit features a dynamic adaptation matrix powered by a 100% Python cross-platform architecture (0% `.sh`, 0% `.bat`, 0% `.bats`). It injects step-by-step instructions and slash commands seamlessly across various AI assistants:

- **Google Antigravity 2.0 (AGY)**: `AGENTS.md` (root instructions) + `.agents/skills/` (modular skills) + `.agents/rules/` (project rules).
- **Claude Code**: `CLAUDE.md` and skill integration.
- **GitHub Copilot**: `.github/copilot-instructions.md` and `.github/prompts/speckit.*.prompt.md`.
- **Cursor**: `.cursorrules` and `.cursor/rules/`.
- **Gemini CLI**: `.gemini/GEMINI.md`.
- **ChatGPT / Custom GPTs**: `CHATGPT.md`.
