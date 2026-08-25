---
name: sdd-clarify
description: Phase 2: Audits and resolves ambiguities, technical risks, and architectural trade-offs (clarify.md).
---

# SDD Clarify — Ambiguity Resolution & Risk Audit

This skill executes **Phase 2** of the Spec-Driven Development (SDD) lifecycle. It audits `spec.md` to identify underspecified requirements, technical risks, and records architectural decisions in `clarify.md`.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Coordinates ambiguity identification.
2. 🛠️ **Ambiguity Resolution Specialist**: Analyzes boundary conditions and formulates clarifying questions.
3. 🔍 **Risk Audit QA Agent**: Verifies that all critical technical risks have mitigation strategies.

## 📋 Execution Steps
1. **Inspect Active Feature**:
   ```bash
   sdd feature
   ```
2. **Generate Clarifications & Resolve Decisions**:
   - Write `.specify/specs/<feature>/clarify.md`.
   - Log decisions under `[Q-001]` format.
3. **Advance Phase**:
   ```bash
   sdd clarify
   ```
