# SpecOps Engine

**SpecOps Engine** is a decoupled monorepo containing three independent, modular tools:

1. **`rules` (`packages/rules/`)**: Autonomous Software Engineering Standards Catalog (28 canonical rules: SOLID, DDD, Clean Architecture, Testing, Security, All Stacks) & Interactive Multi-Agent Reversible Injector (`rules`).
2. **`spec` (`packages/spec/`)**: AI Governance, Spec-Driven Development (SDD), and deterministic verification engine for coding agents (`spec`).
3. **`workspace` (`packages/workspace/`)**: Workspace tools, Git worktree helpers, and local DevOps utilities (`ws`).

```
cucco-specops-engine/
├── packages/
│   ├── rules/                 # Engineering Standards Catalog & Reversible Injector (CLI `rules`)
│   │   ├── src/rules/
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

### 1. Engineering Standards Catalog (`rules`)

Run the interactive TUI assistant to configure your agents globally or locally:

```bash
# Direct interactive TUI (Menu driven, zero flags needed)
PYTHONPATH=packages/rules/src python3 -m rules.cli

# List all 28 canonical rules
PYTHONPATH=packages/rules/src python3 -m rules.cli list
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


