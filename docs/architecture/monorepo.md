# Cucco SpecOps Engine Monorepo Architecture

This document describes the architectural design of the **Cucco SpecOps Engine** monorepo, applying principles of **Clean Architecture**, **SOLID**, **Domain-Driven Design (DDD)**, **DRY**, and **YAGNI**.

---

## 🏛️ 1. Decoupled Autonomous Packages

The monorepo is structured into 3 autonomous packages and a centralized modular rules catalog:

```
cucco-specops-engine/
├── rules/                  # Modular Engineering Rules Catalog (Global & Scoped)
├── packages/
│   ├── common/             # Subproject 0: Shared base utilities, typing, subprocess, parsers (cucco-common)
│   ├── workspace/          # Subproject 1: Deterministic workspace manager & CLI `ws` (cucco-workspace)
│   └── sdd/                # Subproject 2: AI Governance engine & CLI `sdd` (cucco-sdd)
├── docs/                   # Cross-cutting architectural documentation (DRY links)
├── install.py              # Interactive multi-agent installer
├── uninstall.py            # Deterministic uninstaller
└── pyproject.toml          # Monorepo root build configuration
```

---

## ⚙️ 2. Core Architectural Invariants

1. **Legacy layering**: `packages/common` provides foundation utilities and `packages/sdd` contains the former governance engine. The old workspace and DevOps implementation is frozen under `cucco-devops/`; it is not part of the v2 governance architecture.
2. **Deterministic Quality & Zero AI Hallucination**: Heavy build, test, and container operations execute via pure Python CLI wrappers (`ws build`, `ws hooks`, `sdd verify`) in milliseconds.
3. **Single Source of Truth (DRY)**: Engineering standards reside exclusively in `rules/` and compile automatically into native agent formats (.mdc, CLAUDE.md, AGENTS.md).
