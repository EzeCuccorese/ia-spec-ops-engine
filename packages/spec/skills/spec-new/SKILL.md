---
name: spec-new
description: "Interactive Spec-Driven Development assistant. Prompts for base branch and worktree isolation, validates project baseline tests, conducts a mandatory popup modal interview (ask_question) on edge cases, and writes formal @s-tagged Gherkin scenarios."
---

# Spec New Assistant Skill (Pre-Flight & Modal Interview Gate)

## 🛑 Critical Invariants
1. **MANDATORY POPUP MODALS**: You are STRICTLY FORBIDDEN from dumping questions as plain markdown text in the chat. You MUST invoke your platform's interactive modal question tool (`ask_question` in Antigravity / Gemini, or `AskFollowupQuestion` in Claude Code).
2. **PRE-FLIGHT BASELINE INTEGRITY**: You MUST execute `spec preflight` to ensure the base branch is up-to-date and all baseline tests pass. If baseline tests fail, STOP immediately and do NOT proceed.
3. **NEVER run in one-shot**: Do NOT advance to `spec plan`, `spec tasks`, or write production code during `spec new`.
4. **SCENARIO TRACEABILITY**: Every acceptance scenario in `spec.md` must be tagged with `@s1`, `@s2`... for automated traceability auditing.

## Phase 0: Pre-Flight Modal Gate (ask_question)
Before touching any code or initializing the feature, invoke `ask_question` with:
- **Pregunta 1 (Rama Base)**: "¿De qué rama base salimos para esta feature?"
  - Options: Provide the detected current/trunk branch (e.g. `(Recommended) Rama actual (<branch>)`, `main`, `develop`).
- **Pregunta 2 (Nombre de Rama)**: "¿Nombre de la nueva rama / feature?"
  - Options: `(Recommended) feature/<slug>`, `fix/<slug>`, `spike/<slug>`.
- **Pregunta 3 (Aislamiento en Worktree)**: "¿Deseas aislar el feature en un Git Worktree nuevo?"
  - Options: `(Recommended) Sí, crear Git Worktree aislado con symlinks de dependencias`, `No, trabajar sobre el directorio actual`.

## Phase 1: Deterministic Pre-Flight Execution
1. Run `spec preflight "<feature-name>" --from "<base_branch>" --branch "<feature_branch>" [--worktree] --json`.
2. Inspect the JSON result:
   - If `"status": "FAIL"`: **STOP IMMEDIATELY**. Report the baseline failure and evidence path to the user. Do not proceed until the base branch is fixed.
   - If `"status": "READY"`: Note the target directory (`worktree_path`). All subsequent work for this feature takes place inside `worktree_path`.

## Phase 2: Conduct Requirements Modal Interview (ask_question)
Inside the target feature directory, analyze the project domain and invoke `ask_question` with 3 to 5 targeted, incisive questions:
- **Questions Structure**:
  - `question`: Concise question title (e.g., "Granularidad de Probes y Endpoints", "Chequeo de dependencias y fallas", "Contrato y formato de error JSON").
  - `options`: 2 to 4 realistic technical alternatives formatted as user decisions. Prefix the best practice option with `(Recommended)`.
  - `is_multi_select`: `true` for combinable items, `false` for mutually exclusive choices.
- The UI will render the interactive popup modal. Execution automatically blocks until the human clicks Submit.

## Phase 3: Synthesize into spec.md (After Modal Submit)
1. Read the user's answers returned by `ask_question`.
2. Populate `.spec/specs/<feature-slug>/spec.md` with:
   - **User Story**: Persona, Goal, Business Value.
   - **Concrete Acceptance Criteria**: Exhaustive Gherkin scenarios (`Given / When / Then`) covering happy paths, timeout/error modes, and status codes.
   - Tag each scenario with stable identifiers `@s1`, `@s2`... for automated test traceability.
   - **Formal Data Contracts**: Structured schemas / models.
3. Present a brief summary of the updated specification in the chat.
4. **STOP**: Ask: *"¿Apruebas esta especificación formal para avanzar a la fase de planificación (`spec-plan`)?"*. Wait for user sign-off.
