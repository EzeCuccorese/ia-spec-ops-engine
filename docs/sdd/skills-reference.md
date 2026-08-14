# Catálogo Canónico de Habilidades SDD (14 Skills) y Matriz de Subagentes

Este documento describe el catálogo unificado de **14 Habilidades Especializadas de Spec-Driven Development (SDD)**, sus comandos, entregables y la **Matriz de Subagentes Especialistas** que operan bajo la célula multi-agente (`invoke_subagent`).

Todas las habilidades residen en el subproyecto [`packages/sdd/skills/`](file://~/projects/devscripts/packages/sdd/skills/).

---

## 👥 1. Matriz de Subagentes Especialistas por Fase (Célula Multi-Agente)

| Fase SDD | Comando | Agente Especialista (`invoke_subagent`) | Agente Validador QA (`invoke_subagent`) | Entregable Principal |
| :--- | :--- | :--- | :--- | :--- |
| **1. sdd-specify** | `/sdd-specify <feature>` | `Product Owner Agent` | `QA Business Auditor` | `.specify/specs/<feature>/spec.md` |
| **2. sdd-clarify** | `/sdd-clarify` | `Ambiguity Resolution Specialist` | `Risk Audit QA Agent` | `.specify/specs/<feature>/clarify.md` |
| **3. sdd-plan** | `/sdd-plan` | `Software Architect Agent` | `Contract Validator QA` | `.specify/specs/<feature>/plan.md` |
| **4. sdd-checklist** | `/sdd-checklist` | `Quality Gate Specialist` | `DoD Compliance QA` | `.specify/specs/<feature>/checklist.md` |
| **5. sdd-tasks** | `/sdd-tasks` | `Lead Tech Planner Agent` | `Task Atomization QA` | `.specify/specs/<feature>/tasks.md` |
| **6. sdd-analyze** | `/sdd-analyze` | `Static Consistency Auditor` | `Cross-Artifact QA Agent` | `.specify/history/analysis-*.json` |
| **7. sdd-exec** | `/sdd-exec` | `Worker Implementation Agent` | `QA Code Reviewer Agent` | Código fuente & `.specify/history/` |
| **8. sdd-converge**| `/sdd-converge` | `Release Manager Agent` | `Gherkin Verification QA` | PR en GitHub & `.specify/feature.json` |

---

## 🔄 2. Las 8 Fases Canónicas del Ciclo de Vida

| Habilidad | Propósito Principal | Enlace |
|---|---|---|
| `sdd-specify` | Redacta la especificación funcional con historias de usuario, Gherkin y NFRs en `spec.md`. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-specify/SKILL.md) |
| `sdd-clarify` | Resuelve ambigüedades, evalúa riesgos y registra decisiones en `clarify.md`. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-clarify/SKILL.md) |
| `sdd-plan` | Diseña el blueprint técnico, contratos de API formales y esquemas de datos en `plan.md`. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-plan/SKILL.md) |
| `sdd-checklist` | Define los Quality Gates, métricas de cobertura y Definition of Done en `checklist.md`. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-checklist/SKILL.md) |
| `sdd-tasks` | Desglosa la feature en tareas atómicas ejecutables en `tasks.md`. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-tasks/SKILL.md) |
| `sdd-analyze` | Audita estáticamente la consistencia cruzada entre todos los artefactos generados. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-analyze/SKILL.md) |
| `sdd-exec` | Orquesta la ejecución de tareas con Agente Worker (implementación) y Agente QA (validación). | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-exec/SKILL.md) |
| `sdd-converge` | Verifica el cumplimiento de todos los criterios de aceptación y prepara el PR. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-converge/SKILL.md) |

---

## 🛠️ 3. Las 6 Habilidades Especializadas de Soporte

| Habilidad | Comando | Propósito Principal | Enlace |
|---|---|---|---|
| `sdd-quick` | `/sdd-quick <descripcion>` | Vía rápida atómica para resolución de bugs o parches pequeños sin la ceremonia completa. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-quick/SKILL.md) |
| `sdd-audit` | `/sdd-audit [--deep] [--scope]` | Audita deuda técnica, anti-patrones y genera planes de ataque con comandos copy-paste. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-audit/SKILL.md) |
| `sdd-doc` | `/sdd-doc [--full] [--fix]` | Motor autónomo de documentación siguiendo el principio DRY (Plan ➔ Aprobación ➔ Ejecución). | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-doc/SKILL.md) |
| `sdd-init` | `/sdd-init` | Inicializa la estructura `.specify/`, detecta el stack tecnológico y despliega adaptadores de IA. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-init/SKILL.md) |
| `sdd-verify` | `/sdd-verify` | Ejecuta la suite de verificación determinista (linters, tests, secretos y confirmaciones GET). | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-verify/SKILL.md) |
| `sdd-constitution` | `/sdd-constitution` | Configura y mantiene la constitución técnica y reglas maestras del proyecto. | [`SKILL.md`](file://~/projects/devscripts/packages/sdd/skills/sdd-constitution/SKILL.md) |
