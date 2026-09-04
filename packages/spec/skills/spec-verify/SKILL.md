---
name: spec-verify
description: "Executes deterministic verification checks, audits evidence, and reports results to the human before any closure."
---

# Spec Verify Assistant Skill (Mandatory Evidence Audit)

## Workflow
1. Execute `spec verify` using the command runner.
2. Read the execution report and JSON evidence under `.spec/evidence/<feature-slug>/`.
3. **Analyze and Report**:
   - If status is `FAIL`: Present the exact failed assertion, stderr traceback, and affected file. Propose the minimal fix and ask the user for guidance.
   - If status is `PASS`: Present the passed checks (linter, unit tests, coverage, and scenario traceability). If mutation testing is configured, present the mutation score.
4. **STOP**: Never call `spec finish` automatically. Always present the verified evidence and ask the user for authorization to seal the feature.
