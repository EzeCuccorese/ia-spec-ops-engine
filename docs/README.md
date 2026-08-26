# Cucco SpecOps Engine Documentation

> **Legacy documentation:** these pages describe the pre-v2 engine and may contain unverified
> capability claims. Current behavior is documented under [`next/docs/`](../next/docs/).

Welcome to the central documentation hub for **Cucco SpecOps Engine**.

This documentation adheres to the **Single Source of Truth (DRY)** principle: detailed CLI references reside directly within their respective packages to prevent stale duplication.

---

## 🧭 Navigation Index

### 📦 1. Autonomous Packages
- [**cucco-common (`packages/common/`)**](../packages/common/README.md): Shared base utilities, typing, safe subprocess wrappers, frontmatter parsers, and project stack detection.
- [**Frozen DevOps archive (`cucco-devops/`)**](../cucco-devops/README.md): Legacy workspace, Kubernetes, worktree, build, and local-service tooling. It is outside the AI-governance and SDD roadmap.
- [**cucco-sdd (`packages/sdd/`)**](../packages/sdd/README.md): AI governance engine (`sdd`), 8-phase lifecycle, FastMCP server (`sdd mcp`), Dynamic context matcher (`sdd match-rules`), AST contract auditor, and self-healing test harness.

---

### 📋 2. Engineering Rules Catalog
- [**Modular Rules Catalog (`rules/`)**](../rules/README.md):
  - **Global Rules (`rules/global/`)**: Agent interaction, Conventional Commits, Zero AI mentions, security/privacy, and SDD lifecycle.
  - **Scoped Rules (`rules/scoped/`)**: Java/Spring, Python, TypeScript, React, Go, Rust, DevOps/K8s, Testing, Database Migrations, APIs, and Observability.

---

### 🏛️ 3. Architecture & Methodology
- [**Monorepo Architecture**](architecture/monorepo.md): Clean Architecture, SOLID, DDD, DRY, and package decoupling.
- [**SDD Lifecycle Step-by-Step**](sdd/lifecycle.md): Detailed 8-phase lifecycle guide with Mermaid workflow diagrams.
- [**SDD Multi-Agent Architecture**](sdd/architecture.md): Specialized agent cells, execution invariants, MCP, and Self-Healing harness.
- [**SDD Skills Catalog & Agent Matrix**](sdd/skills-reference.md): Catalog of 14 canonical skills and specialized subagent pairings.

---

## ⚡ Quick Setup
- **Interactive Multi-Agent Setup**: [`python3 install.py`](../install.py)
- **Deterministic Uninstallation**: [`python3 uninstall.py`](../uninstall.py)
