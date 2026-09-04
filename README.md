# SpecOps Engine

**SpecOps Engine** is a decoupled monorepo containing three independent, modular tools:

1. **`ai-governance` (`packages/ai-governance/`)**: Software Engineering Standards Catalog (28 canonical rules), Runtime Context Frugality (test trimming & listing condensation), Telemetry & Ritmo Pacing, Lightweight Session State, and Zero-Overhead Tools (`governance`, `rules`, `frugal`, `statusline`, `progreso`, `jira`, `confluence`).
2. **`spec` (`packages/spec/`)**: AI Governance, Spec-Driven Development (SDD), and deterministic verification engine for coding agents (`spec`).
3. **`workspace` (`packages/workspace/`)**: Workspace tools, Git worktree helpers, and local DevOps utilities (`ws`).

```
cucco-specops-engine/
├── packages/
│   ├── ai-governance/         # Standards, Frugality, Telemetry, Ritmo, Session Tracking
│   │   ├── src/ai_governance/
│   │   ├── catalog/           # 28 canonical engineering rules (Core, Stacks, Infra, Docs)
│   │   ├── tests/
│   │   └── pyproject.toml
│   │
│   ├── spec/                  # AI Governance & Spec-Driven Development (CLI `spec`)
│   │   ├── src/spec/
│   │   ├── tests/
│   │   ├── docs/
│   │   └── pyproject.toml
│   │
│   └── workspace/             # DevOps & Workspace Management Tools (CLI `ws`)
│       ├── src/workspace_engine/
│       ├── tests/
│       ├── docs/
│       └── pyproject.toml
│
├── pyproject.toml             # Root monorepo orchestrator
└── README.md
```

---

## ⚡ Quick Start

### 1. AI Governance & Standards (`governance` / `rules`)

Run the interactive TUI assistant or inspect standards and ritmo pacing:

```bash
# Governance Master CLI
PYTHONPATH=packages/ai-governance/src python3 -m ai_governance.cli --help

# List all 28 canonical rules
PYTHONPATH=packages/ai-governance/src python3 -m ai_governance.rules.cli list

# Calculate business-day budget pacing (Ritmo)
PYTHONPATH=packages/ai-governance/src python3 -m ai_governance.cli ritmo --budget 150 --spent 30
```

---

### 2. AI Governance & SDD Engine (`spec`)

Run `spec` directly or against any target repository:

```bash
export SPEC="PYTHONPATH=$PWD/packages/spec/src python3 -m spec"
$SPEC doctor
$SPEC init --root /path/to/project
$SPEC agent install --root /path/to/project
$SPEC new "User Authentication" --root /path/to/project
$SPEC plan --root /path/to/project
$SPEC tasks --root /path/to/project
$SPEC work --root /path/to/project
$SPEC verify --root /path/to/project
$SPEC finish --root /path/to/project
```

---

### 3. Workspace & DevOps Engine (`ws`)

Run `ws` for local development utilities:

```bash
PYTHONPATH=packages/workspace/src python3 -m workspace_engine.cli.main --help
```

---

## 🧪 Testing

Execute all test suites hermetically across all packages:

```bash
python3 -m pytest
```


