---
name: sdd-init
description: Initializes SDD workspace with hybrid protocol (Deterministic CLI + Dynamic AI Discovery & Constitution).
---

# SDD Init — Hybrid SDD Workspace Initialization

Initializes the Spec-Driven Development (SDD) workspace, auto-detects the project tech stack, creates the technical constitution, and deploys Multi-AI adapters.

## 📋 Execution Steps
1. **Run Deterministic Initialization**:
   ```bash
   sdd init
   ```
2. **Dynamic Repository Audit**:
   - Inspects manifests (`pyproject.toml`, `package.json`, `pom.xml`, `Cargo.toml`, etc.).
   - Discovers linters, test commands, and architectural conventions.
3. **Enrich Constitution**:
   - Injects discoveries into `.specify/constitution/constitution.md`.
