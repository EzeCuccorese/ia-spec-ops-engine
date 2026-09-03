---
name: spec-new
description: "Interactive Spec-Driven Development assistant. Initializes a feature specification, conducts a mandatory popup modal interview (ask_question) on edge cases, and writes formal Gherkin scenarios and contracts."
---

# Spec New Assistant Skill (Mandatory Modal Interview Gate)

## 🛑 Critical Invariants
1. **MANDATORY POPUP MODAL**: You are STRICTLY FORBIDDEN from printing interview questions as plain markdown text in the chat. You MUST invoke your platform's interactive modal question tool (`ask_question` in Antigravity / Gemini, or `AskFollowupQuestion` in Claude Code).
2. **NEVER run in one-shot**: Do NOT advance to `spec plan`, `spec tasks`, or write production code during `spec new`.
3. **NEVER assume defaults**: Even for standard features (e.g. Healthcheck, CRUD, Auth), you must trigger the modal popup to let the human confirm architectural decisions and failure modes.

## Phase 1: Initialize Feature
1. Run `spec new "<feature-name>" --description "<brief description>"`.
2. Read `.spec/specs/<feature-slug>/spec.md`.

## Phase 2: Conduct Modal Interview (ask_question)
Invoke the `ask_question` tool with 3 to 5 targeted, high-impact questions:
- **Questions Structure**:
  - `question`: Concise question title (e.g., "Probes y granularidad", "Chequeo de dependencias y fallas de PostgreSQL", "Contrato y formato de error JSON").
  - `options`: 2 to 4 realistic technical alternatives formatted as user decisions. Prefix the best practice option with `(Recommended)`.
  - `is_multi_select`: `true` for combinable items, `false` for mutually exclusive choices.
- The UI will render an interactive popup modal with checkboxes/radio buttons and a text write-in area. Execution automatically blocks until the human clicks Submit.

## Phase 3: Synthesize into spec.md (After Modal Submit)
1. Read the user's answers returned by `ask_question`.
2. Populate `.spec/specs/<feature-slug>/spec.md` with:
   - **User Story**: Persona, Goal, Business Value.
   - **Concrete Acceptance Criteria**: Exhaustive Gherkin scenarios (`Given / When / Then`) covering happy paths, timeout/error modes, and status codes. Tag each scenario with stable identifiers `@s1`, `@s2`... for automated test traceability.
   - **Formal Data Contracts**: Pydantic models, TypeScript types, or JSON schemas.
3. Present a brief summary of the updated specification in the chat.
4. **STOP**: Ask: *"¿Apruebas esta especificación formal para avanzar a la fase de planificación (`spec-plan`)?"*. Wait for user sign-off.
