---
name: sdd-exec
description: Phase 7: Iterative multi-agent execution with Worker (Test-First) and QA Reviewer with Self-Healing harness.
---

# SDD Exec — Iterative Multi-Agent Execution & Self-Healing

This skill executes **Phase 7** of the Spec-Driven Development (SDD) lifecycle. It executes tasks sequentially using an adversarial Worker + QA Reviewer pairing with automatic Self-Healing for test failures.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Coordinates task progression (`sdd harness run`).
2. 🛠️ **Worker Implementation Agent**: Implements contracts and writes unit tests (Red -> Green).
3. 🔍 **QA Code Reviewer Agent**: Audits diffs, runs linters, tests, and security scans.

## 📋 Execution Steps
1. **Check Task Queue**:
   ```bash
   sdd harness status
   ```
2. **Run Harness**:
   ```bash
   sdd harness run
   ```
3. **Log Worker & QA Progress**:
   ```bash
   sdd harness log-worker --task-id "<ID>" --summary "<summary>"
   sdd harness log-qa --task-id "<ID>" --summary "<summary>" --passed
   ```
