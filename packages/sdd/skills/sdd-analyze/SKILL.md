---
name: sdd-analyze
description: Phase 6: Static consistency audit and AST contract validation across all specification artifacts.
---

# SDD Analyze — Static Cross-Artifact & AST Audit

This skill executes **Phase 6** of the Spec-Driven Development (SDD) lifecycle. It performs static analysis across `spec.md`, `clarify.md`, `plan.md`, `checklist.md`, and `tasks.md` to verify internal consistency before implementing production code.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Coordinates audit execution.
2. 🛠️ **Static Consistency Auditor**: Checks schema compatibility and contract completeness.
3. 🔍 **Cross-Artifact QA Agent**: Validates that every task maps to specification requirements.

## 📋 Execution Steps
1. **Run Static Consistency Audit**:
   ```bash
   sdd analyze
   ```
2. **Verify AST Contracts**:
   - Verifies AST integrity and reports any contract mismatches.
