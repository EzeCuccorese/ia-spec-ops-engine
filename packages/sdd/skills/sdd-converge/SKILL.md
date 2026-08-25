---
name: sdd-converge
description: Phase 8: Final convergence verification, Gherkin acceptance validation, checklist sign-off, and PR creation.
---

# SDD Converge — Final Convergence & Pull Request

This skill executes **Phase 8** of the Spec-Driven Development (SDD) lifecycle. It performs end-to-end acceptance testing, signs off the Definition of Done checklist, and creates the Pull Request via `gh` CLI.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Coordinates final release checks.
2. 🛠️ **Release Manager Agent**: Runs final test suites and prepares PR summary.
3. 🔍 **Gherkin Verification QA**: Verifies all scenarios pass against the implemented code.

## 📋 Execution Steps
1. **Verify Convergence**:
   ```bash
   sdd converge
   ```
2. **Finalize Feature & Create Pull Request**:
   ```bash
   sdd finish
   ```
