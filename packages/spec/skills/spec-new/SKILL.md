---
name: spec-new
description: "Interactive Spec-Driven Development assistant. Initializes a feature specification, conducts a mandatory rigorous interview on edge cases, and writes formal Gherkin scenarios and contracts."
---

# Spec New Assistant Skill (Mandatory Gate & Rigorous Interview)

## 🛑 Critical Rule: Zero Assumption & Mandatory Stop
1. **NEVER run in one-shot**: You are STRICTLY FORBIDDEN from running `spec plan`, `spec tasks`, or writing code during `spec new`.
2. **NEVER assume defaults**: Even for seemingly simple tasks (e.g. Healthcheck, CRUD), you must never guess edge cases, error codes, timeouts, or schemas without grilling the human.

## Phase 1: Initialize & Investigate
1. Run `spec new "<feature-name>" --description "<brief description>"`.
2. Read `.spec/specs/<feature-slug>/spec.md`.
3. **STOP IMMEDIATELY**. Do not edit files or advance stages.
4. **Conduct a Mandatory Incisive Interview** in the chat. You MUST ask 3 to 5 deep, targeted questions covering:
   - **Edge Cases & Failure Modes**: What happens when dependencies (DB, third-party APIs, cache) fail, timeout, or return unexpected data?
   - **Exact Data Contracts**: What exact fields, types, headers, and HTTP status codes (RFC 7807 problem details) must be returned?
   - **Security & Validation**: What validation rules, sanitization, rate limits, or auth checks apply?
   - **Invariants & Anti-Patterns**: What must *never* happen in this feature?

## Phase 2: Spec Drafting (Only After Human Answers)
1. Once the user replies in the chat, synthesize their answers into `.spec/specs/<feature-slug>/spec.md`:
   - **User Story**: Persona, Goal, Value.
   - **Incisive Acceptance Criteria**: Multiple concrete Gherkin scenarios (`Given / When / Then`) including happy path, edge cases, and failure modes.
   - **Strict Data Contracts**: Exact schema definitions (Pydantic models, TypeScript types, or JSON schemas).
2. Present the drafted specification to the user.
3. **STOP AGAIN**: Ask: *"¿Apruebas esta especificación formal para avanzar a la fase de planificación (`/spec-plan`)?"*. Wait for explicit user confirmation before proceeding.
