---
name: sdd-tasks
description: Phase 5: Atomizes the technical plan into sequential, executable tasks structured across the 4 SDD Pillars (tasks.md).
---

# SDD Tasks — Executable Task Breakdown

This skill executes **Phase 5** of the Spec-Driven Development (SDD) lifecycle. It breaks down `plan.md` into atomic tasks (`T1`, `T2`, etc.) structured across the 4 SDD Pillars.

## 👥 Multi-Agent Roles
1. 👑 **Lead Orchestrator**: Coordinates task breakdown.
2. 🛠️ **Lead Tech Planner Agent**: Breaks down features into atomic tasks.
3. 🔍 **Task Atomization QA**: Ensures each task is testable and independent.

## 📋 Execution Steps
1. **Inspect Active Feature**:
   ```bash
   sdd feature
   ```
2. **Draft Tasks Breakdown**:
   - Write `.specify/specs/<feature>/tasks.md`.
   - Organize into Pillar 1 (Contracts), Pillar 2 (Test Harness), Pillar 3 (Implementation), Pillar 4 (Quality Gate).
3. **Advance Phase**:
   ```bash
   sdd tasks
   ```
