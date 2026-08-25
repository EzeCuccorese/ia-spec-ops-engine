# SDD Canonical Skills Catalog & Subagent Matrix

Comprehensive catalog of the **14 Specialized Spec-Driven Development (SDD) Skills** and the **Specialized Subagent Matrix** operating under the multi-agent cell (`invoke_subagent`).

---

## 👥 1. Specialized Subagent Matrix by Phase

| SDD Phase | Command | Lead Specialist Subagent | QA Validator Subagent | Primary Deliverable |
| :--- | :--- | :--- | :--- | :--- |
| **1. sdd-specify** | `/sdd-specify <feature>` | `Product Owner Agent` | `QA Business Auditor` | `.specify/specs/<feature>/spec.md` |
| **2. sdd-clarify** | `/sdd-clarify` | `Ambiguity Resolution Specialist` | `Risk Audit QA Agent` | `.specify/specs/<feature>/clarify.md` |
| **3. sdd-plan** | `/sdd-plan` | `Software Architect Agent` | `Contract Validator QA` | `.specify/specs/<feature>/plan.md` |
| **4. sdd-checklist** | `/sdd-checklist` | `Quality Gate Specialist` | `DoD Compliance QA` | `.specify/specs/<feature>/checklist.md` |
| **5. sdd-tasks** | `/sdd-tasks` | `Lead Tech Planner Agent` | `Task Atomization QA` | `.specify/specs/<feature>/tasks.md` |
| **6. sdd-analyze** | `/sdd-analyze` | `Static Consistency Auditor` | `Cross-Artifact QA Agent` | `.specify/history/analysis-*.json` |
| **7. sdd-exec** | `/sdd-exec` | `Worker Implementation Agent` | `QA Code Reviewer Agent` | Source code & `.specify/history/` |
| **8. sdd-converge**| `/sdd-converge` | `Release Manager Agent` | `Gherkin Verification QA` | GitHub PR & `.specify/feature.json` |

---

## 🔄 2. The 8 Canonical Lifecycle Skills

| Skill | Primary Purpose | Link |
|---|---|---|
| `sdd-specify` | Functional specification with user stories, Gherkin, and NFRs in `spec.md` | [`SKILL.md`](../../packages/sdd/skills/sdd-specify/SKILL.md) |
| `sdd-clarify` | Resolves ambiguities, evaluates technical risks, and logs decisions in `clarify.md` | [`SKILL.md`](../../packages/sdd/skills/sdd-clarify/SKILL.md) |
| `sdd-plan` | Technical blueprint, formal API contracts, and schema definitions in `plan.md` | [`SKILL.md`](../../packages/sdd/skills/sdd-plan/SKILL.md) |
| `sdd-checklist` | Defines Quality Gates, coverage metrics, and Definition of Done in `checklist.md` | [`SKILL.md`](../../packages/sdd/skills/sdd-checklist/SKILL.md) |
| `sdd-tasks` | Breaks down features into atomic executable tasks in `tasks.md` | [`SKILL.md`](../../packages/sdd/skills/sdd-tasks/SKILL.md) |
| `sdd-analyze` | Statically audits cross-artifact consistency and AST contracts | [`SKILL.md`](../../packages/sdd/skills/sdd-analyze/SKILL.md) |
| `sdd-exec` | Orchestrates task execution with Worker (Test-First) and QA Reviewer (Audit) | [`SKILL.md`](../../packages/sdd/skills/sdd-exec/SKILL.md) |
| `sdd-converge` | Verifies full acceptance criteria and prepares PR via `sdd finish` | [`SKILL.md`](../../packages/sdd/skills/sdd-converge/SKILL.md) |

---

## 🛠️ 3. The 6 Specialized Support Skills

| Skill | Command | Primary Purpose | Link |
|---|---|---|---|
| `sdd-quick` | `/sdd-quick <desc>` | Accelerated atomic path for bug fixes and patches | [`SKILL.md`](../../packages/sdd/skills/sdd-quick/SKILL.md) |
| `sdd-audit` | `/sdd-audit [--deep]` | Comprehensive debt audit with copy-paste remediation plans | [`SKILL.md`](../../packages/sdd/skills/sdd-audit/SKILL.md) |
| `sdd-doc` | `/sdd-doc [--full]` | Autonomous documentation engine following DRY principle | [`SKILL.md`](../../packages/sdd/skills/sdd-doc/SKILL.md) |
| `sdd-init` | `/sdd-init` | Initializes `.specify/`, detects tech stack, and deploys AI adapters | [`SKILL.md`](../../packages/sdd/skills/sdd-init/SKILL.md) |
| `sdd-verify` | `/sdd-verify` | Executes deterministic quality gate (linters, tests, secrets) | [`SKILL.md`](../../packages/sdd/skills/sdd-verify/SKILL.md) |
| `sdd-constitution` | `/sdd-constitution` | Manages project architectural invariants and technical constitution | [`SKILL.md`](../../packages/sdd/skills/sdd-constitution/SKILL.md) |
