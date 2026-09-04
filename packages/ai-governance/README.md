# SpecOps AI Governance

**SpecOps AI Governance** is a modular package dedicated to maximizing coding agent efficiency, quality, and token frugality:

1. **Engineering Standards (`rules`)**: 28 canonical software engineering rules (SOLID, DDD, Clean Architecture, Testing, Security) and an interactive reversible multi-agent injector.
2. **Context Frugality (`frugal`)**: Runtime output condensor for test runners (pytest, jest, vitest, go test, cargo test) that eliminates green test spam while preserving failure traces; truncates massive homogeneous listings and large JSON payloads; passive pre-command checks.
3. **Telemetry & Budget Pacing (`statusline` & `ritmo`)**: High-visibility ANSI statusline reading native Claude Code metrics (cost, context %, 5h rate limits) plus business-day budget pacing algorithm inspired by GHDominguez/ritmo.
4. **Lightweight Cross-Session State (`task` / `progreso`)**: Compact JSON state (~300 tokens) and append-only Markdown logs to resume complex multi-repo tasks with zero token waste.
5. **Zero-Overhead Tools (`jira`, `confluence`)**: Lightweight CLI tools formatted in clean Markdown without MCP token tax.

---

## ⚡ Quick Start

```bash
# Unified Governance CLI
python3 -m ai_governance.cli --help

# Engineering Rules Catalog
python3 -m ai_governance.rules.cli list

# Budget Ritmo (business days pacing)
python3 -m ai_governance.cli ritmo --budget 150 --spent 40

# Test Output Frugal Trimming (invoked by Claude Code hook)
frugal --post-bash < payload.json
```
