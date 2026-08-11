# GitHub Copilot Instructions — Spec-Driven Development (Spec-Kit Aligned)

# Spec-Driven Development (SDD) — Core Rules & Step-by-Step Lifecycle

## 1. Strict Step-by-Step Lifecycle (Human Control Checkpoints)
Feature development MUST progress sequentially, requiring human review & sign-off before starting each phase:
1. `/sdd-specify`: Functional specification (`spec.md`).
2. `/sdd-clarify`: Ambiguity resolution & risk analysis (`clarify.md`).
3. `/sdd-plan`: Technical blueprint & formal data contracts (`plan.md`).
4. `/sdd-checklist`: Quality gates & Definition of Done (`checklist.md`).
5. `/sdd-tasks`: Executable task breakdown (`tasks.md`).
6. `/sdd-analyze`: Static cross-artifact consistency audit.
7. `/sdd-exec`: Iterative task execution with Worker Agent and QA Reviewer Agent.
8. `/sdd-converge`: Final convergence verification & Gherkin acceptance criteria check.

*Note*: For bug fixes or minor patches, use `/sdd-quick` exclusively.

## 2. SDD Pillars
- **Contracts First**: Define TypeScript interfaces, Zod schemas, or Java DTOs before implementing logic.
- **Test Harness (Test-First)**: Write unit/integration test (Red) before business logic.
- **Minimal Implementation**: Write minimal code necessary to satisfy contract and pass test (Green).
- **Early Detection**: Run linters and verify post-mutation confirmation reads (GET verification query).

## 3. Git & Security Rules
- **Conventional Commits**: Write commit messages in English (`type(scope): description`) in lowercase, imperative mode.
- **ZERO AI MENTIONS**: Never include phrases like "Generated with AI" or robot emojis 🤖 in PRs, commits, or code comments.
- **Security & Privacy**: Zero hardcoded secrets. Zero PII logged.

## SDD Constitution Reference
Always consult `.specify/constitution/` and active feature state in `.specify/feature.json`.
