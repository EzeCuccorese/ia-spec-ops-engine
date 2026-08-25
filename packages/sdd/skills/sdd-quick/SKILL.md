---
name: sdd-quick
description: Fast-path atomic workflow for bug fixes, small patches, and hotfixes with immediate verification.
---

# SDD Quick — Accelerated Bug Fix & Patch Workflow

This skill provides an accelerated path for minor patches, bug fixes, or hotfixes without requiring the full 8-phase ceremony.

## 📋 Execution Steps
1. **Initialize Quick Spec**:
   ```bash
   sdd quick "<description>"
   ```
2. **Implement Test & Fix**:
   - Write reproducing test (Red).
   - Apply minimal fix (Green).
3. **Verify & Commit**:
   ```bash
   sdd verify
   ```
