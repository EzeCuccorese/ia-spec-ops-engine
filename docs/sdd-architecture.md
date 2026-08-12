# Arquitectura del Sistema Spec-Driven Development (SDD) y Adaptadores Multi-IA

Este documento define formalmente la **arquitectura técnica, patrones de diseño y decisiones de ingeniería** del motor de Spec-Driven Development (SDD) integrado en `devscripts`.

---

## 🏛️ 1. Visión General y Principios de Diseño (El "Por Qué")

### ¿Por qué Spec-Driven Development (SDD)?
El desarrollo asistido por modelos de lenguaje (LLMs / Agentes de IA) tradicionalmente sufre de **alucinaciones de requerimientos, deriva de alcance (*Scope Drift*) y degradación del contexto de memoria** en proyectos complejos. SDD resuelve estos problemas estructurando el proceso de desarrollo en torno a una **Especificación Formal Ejecutable como Fuente Única de Verdad**.

```mermaid
graph TD
    subgraph "Capas de Arquitectura SDD"
        CLI["1. CLI & Interface Layer (devscripts.cli.sdd)"]
        CORE["2. Core Engine Layer (devscripts.sdd.*)"]
        ADAPTERS["3. Multi-AI Adapter Engine (devscripts.adapters.bridge)"]
        SKILLS["4. Global Skills & Customization System (~/.gemini, ~/.agents, ~/.claude)"]
        ISOLATION["5. Execution & Worktree Isolation Layer"]
    end

    CLI --> CORE
    CORE --> ADAPTERS
    ADAPTERS --> SKILLS
    CORE --> ISOLATION
```

---

## 🎯 2. Pilares de Ingeniería de SDD

1. **Contratos Primero (Contracts-First)**:
   - *Por qué*: Las interfaces TypeScript, esquemas Zod o DTOs Java se definen antes de cualquier lógica de negocio. Esto elimina la ambigüedad en los bordes del sistema y proporciona validación estática inmediata.
2. **Harnés de Pruebas Primero (Test Harness First)**:
   - *Por qué*: Se escriben pruebas unitarias e integrales que fallan (RED) antes de implementar el código. Garantiza que la especificación sea ejecutable.
3. **Implementación Mínima (YAGNI / Minimal Scope)**:
   - *Por qué*: Los agentes de IA tienden a agregar abstracciones no solicitadas. SDD restringe las mutaciones al código estrictamente necesario para pasar los tests y cumplir el contrato.
4. **Protocolo Híbrido (Determinismo CLI + Inspección Dinámica de IA)**:
   - *Por qué*: Combina la velocidad e idempotencia de scripts ejecutable Python para la estructura base, con la capacidad razonadora de la IA para descubrir linters, convención de commits y patrones de diseño no documentados.

---

## 🔄 3. Diagrama de Secuencia del Ciclo de Vida (8 Fases)

El desarrollo avanza secuencialmente. Cada fase exige un punto de control humano (*Human Gate Checkpoint*) antes de proceder:

```mermaid
sequenceDiagram
    autonumber
    actor Usuario
    participant IA as Agente IA (Antigravity / agy)
    participant CLI as Devscripts SDD CLI
    participant FS as Repositorio & .specify/

    Usuario->>IA: /sdd-specify <feature-name>
    IA->>CLI: sdd feature set <feature-name>
    CLI->>FS: Actualiza .specify/feature.json
    IA->>FS: Genera .specify/specs/<feature>/spec.md
    IA->>Usuario: Presenta spec.md (Punto de Control 1)
    
    Usuario->>IA: /sdd-clarify
    IA->>FS: Revisa spec.md & genera clarify.md
    IA->>Usuario: Presenta clarify.md (Punto de Control 2)
    
    Usuario->>IA: /sdd-plan
    IA->>FS: Diseña contratos & plan.md
    IA->>Usuario: Presenta plan.md (Punto de Control 3)
    
    Usuario->>IA: /sdd-tasks
    IA->>FS: Desglosa tareas en tasks.md
    
    Usuario->>IA: /sdd-exec
    IA->>CLI: sdd harness next
    CLI->>FS: Ejecuta Worker & QA Reviewer loop
    
    Usuario->>IA: /sdd-converge
    IA->>CLI: sdd verify & test suite
    CLI-->>Usuario: Convergencia Verde ✅ (Listo para Commit/PR)
```

---

## 🔀 4. Flujo de Sincronización Multi-IA y Gestión Global de Habilidades (`sdd sync`)

El comando `sdd sync` garantiza que todas las habilidades y reglas del proyecto se distribuyan homogéneamente en el entorno del usuario:

```mermaid
flowchart TD
    A[sdd sync CLI Command] --> B[Step 1: Editable CLI Package Re-install]
    A --> C[Step 2: Global Skills Installer devscripts.sdd.global_skills]
    A --> D[Step 3: Multi-AI Bridge Export devscripts.adapters.bridge]

    C --> E["~/.gemini/config/skills/ (Antigravity IDE & Gemini CLI)"]
    C --> F["~/.agents/skills/ (Antigravity 2.0 Global)"]
    C --> G["~/.claude/skills/ (Claude Code Global)"]

    D --> H[".agents/skills/ & AGENTS.md (Workspace Local)"]
    D --> I[".claude/agents/ & CLAUDE.md (Claude Local)"]
    D --> J[".github/copilot-instructions.md & prompts (Copilot Local)"]
```

---

## 📁 5. Estructura Persistente de Artefactos `.specify/`

* **`.specify/feature.json`**: Rastreo de estado activo (`active_feature`, `current_phase`, timestamps).
* **`.specify/constitution/`**: Fuente de verdad de la arquitectura del proyecto (`constitution.md`, `memory.md`).
* **`.specify/specs/<feature-name>/`**: Artefactos del ciclo de 8 fases (`spec.md`, `clarify.md`, `plan.md`, `checklist.md`, `tasks.md`).
* **`.specify/history/`**: Registros de auditoría de agentes Worker y QA Reviewer.
* **`.specify/agents.json`**: Registro de adaptadores IA configurados en el proyecto.
