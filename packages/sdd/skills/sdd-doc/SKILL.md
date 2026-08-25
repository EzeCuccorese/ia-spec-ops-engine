---
name: sdd-doc
description: Autonomous documentation engine: scans project, creates DRY documentation update plan, and applies changes upon user approval.
---

# SDD Doc — Autonomous Documentation Engine

Scans the codebase, detects undocumented changes or stale references, generates a documentation plan following the **DRY (Don't Repeat Yourself)** principle, and updates markdown documentation after user approval.

## 📋 Execution Steps
1. **Scan Project & Formulate Plan**:
   - Identifies changed contracts and APIs.
2. **Obtain User Approval**:
   - Halts and presents plan to user.
3. **Apply & Verify Links**:
   - Updates documentation and verifies all relative markdown links.
