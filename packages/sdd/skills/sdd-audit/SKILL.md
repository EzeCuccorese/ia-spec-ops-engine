---
name: sdd-audit
description: Comprehensive codebase audit: detects technical debt, bugs, anti-patterns, memory leaks, and generates remediation plans.
---

# SDD Audit — Codebase Technical Debt & Bug Audit

Performs exhaustive structural and static analysis to identify architectural debt, anti-patterns, security gaps, and unhandled errors, cataloged in `.specify/tech-debt.md`.

## 📋 Execution Steps
1. **Run Full Audit**:
   ```bash
   sdd audit --deep
   ```
2. **Inspect & Remediate**:
   - Generates `.specify/tech-debt.md` with priority matrix and `/sdd-quick` copy-paste commands.
