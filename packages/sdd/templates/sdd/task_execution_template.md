# SDD Task Execution Log Template

## Task Metadata
- **Task ID:** {TASK_ID}
- **Feature Name:** {FEATURE_NAME}
- **Role:** {ROLE}  <!-- Worker | QA Reviewer | Leader -->
- **Timestamp:** {TIMESTAMP}
- **Status:** {STATUS}  <!-- SUCCESS | PASS | FAIL | REMEDIATION_REQUIRED -->

## 1. Scope & Objective
- **Description:** {TASK_DESCRIPTION}
- **Target Files:**
  - `path/to/file.py`

## 2. Execution Summary
- **Contracts Defined/Updated:**
  - Interface or DTO modified.
- **Tests Added/Updated:**
  - Test function or suite executed.
- **Minimal Code Implementation:**
  - Summary of changes implemented (YAGNI).

## 3. Verification & Quality Gates (QA Reviewer Only)
- [ ] Linter pass (`oxlint` / `eslint` / `flake8` / `pytest`)
- [ ] Automated tests pass (`npm test` / `pytest` / `./gradlew test`)
- [ ] Post-mutation confirmation read verified (GET query / DB read)
- [ ] Zero hardcoded secrets & Zero PII logged
- [ ] `checklist.md` items validated

## 4. Findings & Remediation Instructions (if FAIL)
- **Error Summary:** Synthetic high-level description of failure.
- **Actionable Remediation:** Step-by-step fix instructions for Worker Agent.
