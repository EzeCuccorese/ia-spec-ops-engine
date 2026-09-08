---
name: spec-new
description: "Spec-Driven Development assistant for initiating specifications. Verifies project baseline tests, clarifies ambiguous requirements, and writes formal @s-tagged Gherkin scenarios."
---

# Spec New Assistant Skill (Specification Gate)

## 🛑 Critical Invariants
1. **PRE-FLIGHT BASELINE INTEGRITY**: Execute `spec preflight` to ensure the base branch is clean and all baseline tests pass. If baseline tests fail, STOP immediately and report the failure.
2. **NEVER run in one-shot**: Do NOT advance to `spec plan`, `spec tasks`, or write production code during `spec new`.
3. **SCENARIO TRACEABILITY**: Every acceptance scenario in `spec.md` must be tagged with `@s1`, `@s2`... for automated traceability auditing.
4. **ALIGNMENT ON AMBIGUITY**: When requirements or edge cases are underspecified, clarify them with the user before finalizing the specification.

## Workflow

### Phase 1: Pre-Flight Baseline Execution
1. Run `spec preflight "<feature-name>" [--from "<base_branch>"] [--branch "<feature_branch>"] [--worktree] --json`.
2. Inspect the JSON result:
   - If `"status": "FAIL"`: **STOP IMMEDIATELY**. Report the baseline failure and evidence path to the user. Do not proceed until the base branch is healthy.
   - If `"status": "READY"`: Confirm target directory and active feature.

### Phase 2: Requirements Clarification
1. Inspect existing code, interfaces, and user request.
2. If there are ambiguous tradeoffs, missing edge-case behaviors, or architectural unknowns, present concise questions with realistic options to align with the user.
3. If the user request already specifies requirements exhaustively, proceed directly to specification drafting.

### Phase 3: Draft Formal Specification (`spec.md`)
1. Populate `.spec/specs/<feature-slug>/spec.md` with:
   - **User Story**: Persona, Goal, Value proposition.
   - **Concrete Acceptance Criteria**: Exhaustive Gherkin scenarios (`Given / When / Then`) covering happy paths, edge cases, error modes, and boundaries.
   - Tag each scenario with stable identifiers `@s1`, `@s2`... for automated test traceability.
   - **Data Contracts**: Explicit schemas, request/response models, or CLI behaviors.
2. Present a concise summary of the specification.
3. **STOP**: Ask: *"Do you approve this formal specification to advance to the planning phase (`spec-plan`)?"*. Wait for user sign-off.
