---
name: spec-new
description: "Interactive Spec-Driven Development assistant. Initializes a feature specification, conducts an intelligent requirements interview, and writes rigorous Gherkin scenarios and data contracts."
---

# Spec New Assistant Skill

## Workflow
When the user asks to create or specify a new feature (e.g. `/spec-new "<feature-name>"` or "Let's create a spec for <feature>"):
1. Execute: `spec new "<feature-name>" --description "<description>"` via your command runner tool.
2. Read the newly created `.spec/specs/<feature-slug>/spec.md`.
3. Conduct an interactive interview with the user in the chat:
   - Ask about domain entities, input/output data contracts, and edge cases.
   - Ask about error handling and validation invariants.
4. Update `.spec/specs/<feature-slug>/spec.md` with:
   - **User Story**: As a / I want / So that.
   - **Acceptance Criteria (Gherkin)**: `Given / When / Then` scenarios.
   - **Data Contracts**: Explicit TypeScript types, Pydantic schemas, or Java records.
5. Request user approval on the completed specification before advancing to planning.
