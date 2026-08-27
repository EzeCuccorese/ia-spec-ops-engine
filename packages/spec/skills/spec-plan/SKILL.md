---
name: spec-plan
description: "Generates the architectural implementation plan and atomic task breakdown for the active specification."
---

# Spec Plan Assistant Skill

## Workflow
When the user approves a specification and requests planning (e.g. `/spec-plan`):
1. Execute `spec plan` and `spec tasks`.
2. Read the active `.spec/specs/<feature-slug>/spec.md`.
3. Populate `.spec/specs/<feature-slug>/plan.md` with:
   - Component architecture (Layers, Ports & Adapters, DTOs).
   - Affected files list: `[NEW]`, `[MODIFY]`, `[DELETE]`.
   - Test-First Strategy (Unit tests, Integration tests with Testcontainers/WireMock).
4. Populate `.spec/specs/<feature-slug>/tasks.md` with atomic, sequential implementation steps.
5. Execute `spec work` when ready to begin coding.
