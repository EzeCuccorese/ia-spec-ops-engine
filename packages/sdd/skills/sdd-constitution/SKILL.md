---
name: sdd-constitution
description: "Establece o actualiza la fuente de verdad de la arquitectura del repositorio en .specify/constitution/ (misión, stack tecnológico, arquitectura y reglas de seguridad)."
argument-hint: "(opcional — analiza el repositorio actual)"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Constitution — Architectural Source of Truth

You are executing the **SDD Constitution** skill. This skill analyzes the project and establishes (or updates) the documents serving as the single source of truth for Spec-Driven Development in `.specify/constitution/`.

```
.specify/constitution/
├── index.md           # Main index and change log
├── mission.md         # Mission, Vision, Target Users, and Non-Goals
├── tech-stack.md      # Languages, frameworks, databases, and banned libraries
├── architecture.md    # Architecture principles, module boundaries, and data flow
└── security-rules.md  # OWASP rules, secret management, DB backups, and PII sanitization
```

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Architecture Source Specialist** y al **Constitution Compliance QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Architecture Source Specialist)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Constitution Compliance QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-constitution <parámetros>`).

## 📋 Execution Checklist

1. **Detect root repository and verify existing constitution**
2. **Deep codebase analysis (Manifests, layouts, and patterns)**
3. **Draft initial constitution files**
4. **Interactive section-by-section refinement with developer**
5. **Save and validate structure in `.specify/constitution/`**
6. **Wire constitution into AI instruction files**

---

## Step 1 — Detect Root and Existing State

Get Git repository root:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
CONST_DIR="$REPO_ROOT/.specify/constitution"
echo "CONST_DIR: $CONST_DIR"
```

Verify if prior constitution exists:
- If `$CONST_DIR` exists, read files and offer to iterate over existing documents or rewrite from scratch.
- If missing, proceed to analysis phase.

---

## Step 2 — Deep Codebase Analysis

Examine project searching for:
- Config files and manifests: `package.json`, `pom.xml`, `build.gradle`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Dockerfile`, `compose.yaml`.
- Main directory structures (`src/`, `lib/`, `cmd/`, `test/`, etc.).
- Test suites and configured linters.
- Existing documentation files (`README.md`, `Agent Context`, `docs/`).

---

## Step 3 — Draft Initial Files

Generate in-memory drafts for the 5 base files:

### 1. `index.md`
```markdown
# Project Architecture Constitution

**Status**: 🟢 ACTIVE  
**Last Updated**: {YYYY-MM-DD}  

> Single source of truth for Spec-Driven Development (SDD) in this repository.

## Constitution Documents
- [Mission & Vision](./mission.md) — Project scope and definition.
- [Tech Stack](./tech-stack.md) — Technologies, frameworks, and banned libraries.
- [Architectural Principles](./architecture.md) — Layers, data flow, and patterns.
- [Security & Ops Rules](./security-rules.md) — OWASP, secret management, PII, and backups.
```

### 2. `mission.md`
```markdown
# Mission & Vision

**Mission**: {Core purpose of system}  
**Vision**: {Projected evolution of software}  
**Target Users**: {Audience or consuming services}  
**Non-Goals (What it explicitly does NOT do)**: {Project boundaries}  
```

### 3. `tech-stack.md`
```markdown
# Tech Stack

| Layer | Technology | Rationale / Convention |
|-------|------------|------------------------|
| Language | {Language and version} | {Rationale} |
| Framework | {Web / CLI Framework} | {Rationale} |
| Persistence | {Database / ORM} | {Rationale} |
| Testing | {Runner / Assertions} | {Rationale} |

## Discouraged / Banned Libraries and Patterns
- {Banned library or pattern and reason}
```

### 4. `architecture.md`
```markdown
# Architectural Principles

1. **Contracts First**: Define Zod/DTO schemas/interfaces before coding logic.
2. **Test Harness**: Create automated unit or integration tests before logic implementation.
3. **Minimal Implementation**: Keep code scoped strictly to spec requirements (YAGNI).
4. **Module Boundaries**: {Dependency rules between packages/modules}.
```

### 5. `security-rules.md`
```markdown
# Security and Operations Rules

1. **Secret Protection**: Hardcoding passwords or tokens prohibited. Use environment variables.
2. **Log Privacy**: Never log personal data (PII) or financial data.
3. **Mandatory MongoDB Backup**: Export collection to JSON before mutations and await "OK WRITE" confirmation.
4. **Traceability**: Propagate `X-Request-Id` and `X-Trace-Id` in HTTP headers.
```

---

## Step 4 — Interactive Refinement

Consult developer via structured questions (`AskUserQuestion`) if validation or adjustments are needed for tech stack or architectural rules.

---

## Step 5 — Save Constitution

Write all 5 files to `$CONST_DIR/` using the `Write` tool.

---

## Step 6 — Wire Constitution with AI Instructions

Ensure constitution is referenced in repository main instruction file (`Agent Context`, `AGENTS.md`, or `.cursorrules`):

```markdown
## Constitution (SDD — Source of Truth)
Every spec, plan, and implementation in this repo must align with the constitution.
@.specify/constitution/mission.md
@.specify/constitution/tech-stack.md
@.specify/constitution/architecture.md
@.specify/constitution/security-rules.md
```

Display final summary with location of all generated files.
