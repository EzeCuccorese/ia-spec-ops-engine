# Spec-Driven Development (SDD) Architecture & Multi-Agent Cells

This document details the multi-agent cell architecture, execution invariants, MCP integration, and self-healing test harness of the **Cucco SpecOps Engine**.

---

## 🏛️ 1. Specialized Multi-Agent Cell

Rather than relying on a single generalist agent prone to context drift and hallucination, SDD organizes work into specialized adversarial cells:

```mermaid
flowchart LR
    subgraph CELL ["SDD Multi-Agent Cell"]
        LEADER["👑 Lead Orchestrator Agent"]
        WORKER["🛠️ Worker Agent (Test-First)"]
        QA["🔍 QA Reviewer Agent (Auditor)"]
    end
    GIT[("📦 Git Worktree")]

    LEADER -->|"Assigns Task"| WORKER
    WORKER -->|"Delivers Code & Tests"| QA
    QA -->|"Rejects (Max 3 Retries)"| WORKER
    QA -->|"Approves PASS"| LEADER
    LEADER -->|"Auto-Commit"| GIT

    classDef cellBox fill:#1e293b,stroke:#3b82f6,stroke-width:1.5px,color:#f8fafc;
    classDef gitBox fill:#0f172a,stroke:#10b981,stroke-width:1.5px,color:#f8fafc;
    class LEADER,WORKER,QA cellBox;
    class GIT gitBox;
```

---

## ⚙️ 2. Determinism vs. AI Intelligence

1. **Deterministic Tools (`workspace_engine` & `sdd_engine.harness.verify`)**:
   - Native builds (`ws build`), JDK management (`ws java`), dependency installation, linter validation, and test execution.
   - Millisecond execution, zero hallucination, massive token savings.
2. **Intelligent AI Agents (`packages/sdd/skills/`)**:
   - Domain reasoning, formal schema design, Gherkin drafting, and business logic implementation backed by deterministic tools.

---

## 🔌 3. FastMCP Server & Dynamic Context Matcher

- **FastMCP Server (`sdd mcp`)**: Exposes deterministic tools (`sdd_verify`, `ws_clean`, `sdd_get_rules`, `sdd_feature_status`) over JSON-RPC 2.0 stdio for Claude Code, Cursor, and VS Code.
- **Dynamic Context Matcher (`sdd match-rules`)**: Analyzes git diffs and injects only relevant scoped rules, reducing token consumption by 40% to 75%.
