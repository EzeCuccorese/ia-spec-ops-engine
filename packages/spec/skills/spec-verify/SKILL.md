---
name: spec-verify
description: "Executes deterministic verification checks configured in .spec/verification.json and analyzes execution evidence."
---

# Spec Verify Assistant Skill

## Workflow
When the user or agent finishes writing code/tests and needs to verify (e.g. `/spec-verify`):
1. Execute `spec verify` using the command runner.
2. Read the execution report and evidence path.
3. If status is `FAIL` or `INCOMPLETE`:
   - Inspect stdout/stderr and traceback in the evidence JSON file.
   - Fix the failing code or tests.
   - Re-run `spec verify` until status is `PASS`.
4. If status is `PASS`:
   - Report the passed checks and summary to the user.
