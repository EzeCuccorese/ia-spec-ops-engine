---
name: sdd-checklist
description: Phase 4: Establishes Quality Gates, code coverage targets, and Definition of Done (checklist.md).
---

# SDD Checklist — Quality Gates & Definition of Done

This skill executes **Phase 4** of the Spec-Driven Development (SDD) lifecycle. It defines explicit, measurable quality gates and DoD criteria in `checklist.md`.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Manages DoD boundaries.
2. 🛠️ **Quality Gate Specialist**: Configures code coverage thresholds, linter rules, and security scans.
3. 🔍 **DoD Compliance QA**: Validates that all critical paths have test assertions.

## 📋 Execution Steps
1. **Inspect Active Feature**:
   ```bash
   sdd feature
   ```
2. **Draft Quality Gates**:
   - Write `.specify/specs/<feature>/checklist.md`.
3. **Advance Phase**:
   ```bash
   sdd checklist
   ```
