# SpecOps Engine

**SpecOps Engine** is a decoupled monorepo containing two independent, modular tools:

1. **`spec` (`packages/spec/`)**: AI Governance, Spec-Driven Development (SDD), and deterministic verification engine for coding agents.
2. **`workspace` (`packages/workspace/`)**: Workspace tools, Git worktree helpers, and local DevOps utilities (`ws`).

```
cucco-specops-engine/
├── packages/
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

### 1. AI Governance & SDD Engine (`spec`)

Run `spec` directly or install it:

```bash
# Direct run without installation
PYTHONPATH=packages/spec/src python3 -m spec --help

# Workflow lifecycle against any project
export SPEC="PYTHONPATH=$PWD/packages/spec/src python3 -m spec"
$SPEC doctor
$SPEC init --root /path/to/project
$SPEC agent install --root /path/to/project
$SPEC spec new "User Authentication" --root /path/to/project
$SPEC plan --root /path/to/project
$SPEC tasks --root /path/to/project
$SPEC work --root /path/to/project
$SPEC verify --root /path/to/project
$SPEC finish --root /path/to/project
```

For in-depth documentation, visit [`packages/spec/README.md`](packages/spec/README.md) and [`packages/spec/docs/`](packages/spec/docs/).

---

### 2. Workspace & DevOps Engine (`ws`)

Run `ws` for local development utilities:

```bash
# Direct run without installation
PYTHONPATH=packages/workspace/src python3 -m workspace_engine.cli.main --help

# Workspace doctor & tools
PYTHONPATH=packages/workspace/src python3 -m workspace_engine.cli.main doctor
```

For details, visit [`packages/workspace/README.md`](packages/workspace/README.md).

---

## 🧪 Testing

Execute all test suites hermetically across packages:

```bash
python3 -m pytest
```

