---
name: spec-plan
description: "Generates the architectural implementation plan and atomic task breakdown after grilling the human on technical decisions."
---

# Spec Plan Assistant Skill (Mandatory Architectural Gate)

## 🛑 Critical Rule: Mandatory Architectural Interview & Stop
1. **NEVER start coding**: You are STRICTLY FORBIDDEN from writing production code or running `spec work` in the same turn as `spec plan`.
2. **Challenge Design Decisions**: Verify architectural alignment (Clean Architecture, Ports & Adapters, SOLID) and test strategy before locking the plan.

## Phase 1: Architecture & Test-First Inquiry
1. Verify that `.spec/specs/<feature-slug>/spec.md` is approved.
2. Execute `spec plan` and `spec tasks`.
3. **STOP and Ask Incisive Architectural Questions**:
   - **Component Boundaries**: Which layers (Domain, Application, Infrastructure) will be touched? What new interfaces/ports are needed?
   - **Test-First Strategy**: What unit tests (AAA) and what integration tests (Testcontainers, WireMock, Mocking) will be written *before* implementation?
   - **Database & State**: Are there migrations involved? What is the rollback and backup strategy?
   - **Observability & Logging**: What structured logs, metrics, or trace IDs must be added?

## Phase 2: Plan & Tasks Formulation (After User Response)
1. Populate `.spec/specs/<feature-slug>/plan.md` with:
   - Component & Layer Architecture.
   - Exact affected files: `[NEW]`, `[MODIFY]`, `[DELETE]`.
   - Test-First execution checklist.
2. Populate `.spec/specs/<feature-slug>/tasks.md` with atomic, sequential sub-tasks.
3. Present the plan summary.
4. **STOP AGAIN**: Ask: *"¿Apruebas este plan de implementación para comenzar el desarrollo Test-First (`/spec-work`)?"*. Wait for user confirmation.
