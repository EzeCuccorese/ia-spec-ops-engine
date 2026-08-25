---
name: sdd-plan
description: Phase 3: Technical blueprint, formal data contracts (DTOs/Zod/Pydantic), and architecture design (plan.md).
---

# SDD Plan — Technical Blueprint & Data Contracts

This skill executes **Phase 3** of the Spec-Driven Development (SDD) lifecycle. It produces the technical architecture blueprint, formal data contracts (Zod schemas, Java Records, Pydantic models), and API endpoint definitions in `plan.md`.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Coordinates architectural design.
2. 🛠️ **Software Architect Agent**: Designs formal schemas, component flow, and endpoint contracts.
3. 🔍 **Contract Validator QA**: Ensures contracts satisfy all Gherkin requirements from `spec.md`.

## 📋 Execution Steps
1. **Read Active Feature Specification**:
   ```bash
   sdd feature
   ```
2. **Draft Technical Blueprint**:
   - Write `.specify/specs/<feature>/plan.md`.
   - Define formal schemas, endpoint tables, and sequence diagrams.
3. **Advance Phase**:
   ```bash
   sdd plan
   ```
