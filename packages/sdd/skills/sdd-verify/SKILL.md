---
name: sdd-verify
description: Executes automated verification suite: linters, tests, post-mutation GET confirmation, and secret/PII scanning.
---

# SDD Verify — Automated Deterministic Quality Verification

Executes the automated quality gate verifying linters, unit tests, secret prevention, and post-mutation reads.

## 📋 Execution Steps
1. **Run Full Verification**:
   ```bash
   sdd verify
   ```
2. **Run Scoped Verification on Modified Files**:
   ```bash
   sdd verify --files path/to/file.py
   ```
