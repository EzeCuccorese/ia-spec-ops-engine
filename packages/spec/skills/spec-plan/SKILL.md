---
name: spec-plan
description: "Generates the architectural implementation plan and atomic task breakdown after conducting an interactive modal interview on technical decisions."
---

# Spec Plan Assistant Skill (Mandatory Architecture Gate)

## 🛑 Critical Invariants
1. **INTERACTIVE MODAL INQUIRY**: If there are ambiguous architectural decisions (e.g. Testcontainers vs Mocking, database migrations, caching layer), invoke the interactive modal question tool (`ask_question`) instead of dumping open questions in chat.
2. **NEVER start coding**: Do NOT write production code or execute `spec work` during `spec plan`.

## Phase 1: Architectural Formulation
1. Verify that `.spec/specs/<feature-slug>/spec.md` is approved.
2. Execute `spec plan` and `spec tasks`.
3. If technical tradeoffs exist (e.g. synchronous vs asynchronous DB driver, mock strategy):
   - Invoke `ask_question` with concrete architectural options.

## Phase 2: Plan & Tasks Documentation
1. Populate `.spec/specs/<feature-slug>/plan.md` with:
   - Component & Layer Architecture (Domain, Application, Infrastructure).
   - Affected files list: `[NEW]`, `[MODIFY]`, `[DELETE]`.
   - Test-First Strategy: Unit tests (AAA) and integration tests to be written *before* implementation.
2. Populate `.spec/specs/<feature-slug>/tasks.md` with atomic, sequential sub-tasks.
3. Present the plan summary.
4. **STOP**: Ask: *"¿Apruebas este plan de implementación para comenzar el desarrollo Test-First (`spec work`)?"*. Wait for user confirmation.
