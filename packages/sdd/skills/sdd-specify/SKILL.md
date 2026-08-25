---
name: sdd-specify
description: Phase 1: Defines functional specification (spec.md) with user stories, Gherkin scenarios, and NFRs.
---

# SDD Specify — Functional Specification

This skill executes **Phase 1** of the Spec-Driven Development (SDD) lifecycle. It defines user stories, acceptance criteria formatted in Gherkin (`Given-When-Then`), and non-functional requirements (NFRs) in `.specify/specs/<feature>/spec.md`.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Coordinates feature scope and creates `.specify/feature.json`.
2. 🛠️ **Product Owner Specialist**: Drafts functional specification and Gherkin scenarios.
3. 🔍 **QA Business Auditor**: Reviews Gherkin scenarios for completeness and edge cases.

## 📋 Execution Steps
1. **Validate & Initialize Feature**:
   ```bash
   sdd feature "<feature-name>"
   ```
2. **Draft Specification**:
   - Create `.specify/specs/<feature>/spec.md` using the canonical template.
   - Include user stories, happy path & error Gherkin scenarios, and NFRs.
3. **Advance Phase**:
   ```bash
   sdd specify
   ```
