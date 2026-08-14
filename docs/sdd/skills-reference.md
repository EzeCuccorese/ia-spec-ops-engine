# Catálogo Canónico de Habilidades SDD (14 Skills)

Este documento describe las 14 habilidades especializadas de Spec-Driven Development, estructuradas en las **8 Fases Canónicas del Ciclo de Vida** y las **6 Habilidades Especializadas de Soporte**.

Todas las habilidades residen en el subproyecto [`packages/sdd/skills/`](file://~/projects/devscripts/packages/sdd/skills/).

---

## 🔄 1. Las 8 Fases Canónicas del Ciclo de Vida

| Habilidad | Comando | Propósito Principal |
|---|---|---|
| [`sdd-specify`](file://~/projects/devscripts/packages/sdd/skills/sdd-specify/SKILL.md) | `/sdd-specify <feature>` | Redacta la especificación funcional con historias de usuario, Gherkin y NFRs en `spec.md`. |
| [`sdd-clarify`](file://~/projects/devscripts/packages/sdd/skills/sdd-clarify/SKILL.md) | `/sdd-clarify` | Resuelve ambigüedades, evalúa riesgos y registra decisiones en `clarify.md`. |
| [`sdd-plan`](file://~/projects/devscripts/packages/sdd/skills/sdd-plan/SKILL.md) | `/sdd-plan` | Diseña el blueprint técnico, contratos de API formales y esquemas de datos en `plan.md`. |
| [`sdd-checklist`](file://~/projects/devscripts/packages/sdd/skills/sdd-checklist/SKILL.md) | `/sdd-checklist` | Define los Quality Gates, métricas de cobertura y Definition of Done en `checklist.md`. |
| [`sdd-tasks`](file://~/projects/devscripts/packages/sdd/skills/sdd-tasks/SKILL.md) | `/sdd-tasks` | Desglosa la feature en tareas atómicas ejecutables en `tasks.md`. |
| [`sdd-analyze`](file://~/projects/devscripts/packages/sdd/skills/sdd-analyze/SKILL.md) | `/sdd-analyze` | Audita estáticamente la consistencia cruzada entre todos los artefactos generados. |
| [`sdd-exec`](file://~/projects/devscripts/packages/sdd/skills/sdd-exec/SKILL.md) | `/sdd-exec` | Orquesta la ejecución de tareas con Agente Worker (implementación) y Agente QA (validación). |
| [`sdd-converge`](file://~/projects/devscripts/packages/sdd/skills/sdd-converge/SKILL.md) | `/sdd-converge` | Verifica el cumplimiento de todos los criterios de aceptación y prepara el PR. |

---

## 🛠️ 2. Las 6 Habilidades Especializadas de Soporte

| Habilidad | Comando | Propósito Principal |
|---|---|---|
| [`sdd-quick`](file://~/projects/devscripts/packages/sdd/skills/sdd-quick/SKILL.md) | `/sdd-quick <descripcion>` | Vía rápida atómica para resolución de bugs o parches pequeños sin la ceremonia completa. |
| [`sdd-audit`](file://~/projects/devscripts/packages/sdd/skills/sdd-audit/SKILL.md) | `/sdd-audit [--deep] [--scope]` | Audita deuda técnica, anti-patrones y genera planes de ataque con comandos copy-paste. |
| [`sdd-doc`](file://~/projects/devscripts/packages/sdd/skills/sdd-doc/SKILL.md) | `/sdd-doc [--full] [--fix]` | Motor autónomo de documentación siguiendo el principio DRY (Plan ➔ Aprobación ➔ Ejecución). |
| [`sdd-init`](file://~/projects/devscripts/packages/sdd/skills/sdd-init/SKILL.md) | `/sdd-init` | Inicializa la estructura `.specify/`, detecta el stack tecnológico y despliega adaptadores de IA. |
| [`sdd-verify`](file://~/projects/devscripts/packages/sdd/skills/sdd-verify/SKILL.md) | `/sdd-verify` | Ejecuta la suite de verificación determinista (linters, tests, secretos y confirmaciones GET). |
| [`sdd-constitution`](file://~/projects/devscripts/packages/sdd/skills/sdd-constitution/SKILL.md) | `/sdd-constitution` | Configura y mantiene la constitución técnica y reglas maestras del proyecto. |
