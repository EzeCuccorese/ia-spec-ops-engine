---
name: spec-plan
description: "Generates the architectural implementation plan and atomic task breakdown for approved specifications."
---

# Spec Plan Assistant Skill (Architectural Gate)

## 🛑 Critical Invariants
1. **ARCHITECTURAL CLARITY**: If there are critical architectural tradeoffs or technical decisions, align with the user before finalizing the plan.
2. **NEVER start coding**: Do NOT write production code or execute `spec work` during `spec plan`.
3. **TEST-FIRST DISCIPLINE**: Every task and planned change must follow Uncle Bob's Three Laws of TDD and map directly to `@s` scenarios.

## Workflow

### Phase 1: Architectural Formulation
1. Verify that `.spec/specs/<feature-slug>/spec.md` is approved and complete.
2. Execute `spec plan` and `spec tasks` to initialize the artifact templates.
3. If technical tradeoffs exist (e.g. database driver selection, storage engine, caching vs query), present the alternatives clearly to the user.

### Phase 2: Plan & Tasks Documentation
1. Populate `.spec/specs/<feature-slug>/plan.md` with:
   - Component & Layer Architecture.
   - Affected files list: `[NEW]`, `[MODIFY]`, `[DELETE]`.
   - Test-First Strategy: Unit and integration tests mapped to each `@s` scenario to be written *before* implementation.
   - Risks, boundaries, and rollback plan.
2. Populate `.spec/specs/<feature-slug>/tasks.md` with atomic, sequential sub-tasks referencing the `@s` scenarios they cover.
3. Present the plan summary.
4. **STOP**: Ask: *"Do you approve this implementation plan to begin Test-First development (`spec work`)?"*. Wait for user confirmation.
