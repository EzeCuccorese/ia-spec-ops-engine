# Arquitectura SDD y Adaptadores Multi-IA

El motor de **Spec-Driven Development (SDD)** en el toolkit opera sobre artefactos estandarizados en Markdown y archivos de estado dentro de `.specify/`:

- **`.specify/feature.json`**: Estado de seguimiento del feature activo (`active_feature`, `current_phase`, timestamps).
- **`.specify/constitution/`**: Principios del proyecto, reglas de arquitectura y estándares del tech stack (`index.md`, `mission.md`, `tech-stack.md`, `architecture.md`).
- **`.specify/specs/<nombre-del-feature>/`**: Artefactos del ciclo de vida SDD de 8 fases:
  - `spec.md`: Especificación funcional con historias de usuario y escenarios Gherkin.
  - `clarify.md`: Resolución de ambigüedades y análisis de quality gates.
  - `plan.md`: Blueprint técnico con diagramas de secuencia Mermaid y contratos formales (Zod/DTOs).
  - `checklist.md`: Quality Gates, Definition of Done (DoD) y lecturas de confirmación GET tras mutación.
  - `tasks.md`: Desglose de tareas ejecutables ordenadas estrictamente a través de los 4 pilares SDD.
- **`.specify/memory.md`**: Memoria histórica acumulada de decisiones de arquitectura.
- **`.specify/history/`**: Registros de ejecución persistentes para agentes Worker, QA Reviewer y Leader (`<timestamp>-<task_id>-<rol>.md`).
- **`.specify/tech-debt.md`**: Inventario de deuda técnica identificada.

---

## Ciclo de Vida Paso a Paso y Harness de Ejecución

El desarrollo de features avanza de forma secuencial, requiriendo revisión y aprobación explícita humana en cada punto de control:

```
sdd specify  -->  sdd clarify  -->  sdd plan  -->  sdd checklist  -->  sdd tasks  -->  sdd analyze  -->  sdd exec (harness)  -->  sdd converge
```

Durante la Fase 7 (`sdd exec`), el **Harness de Ejecución Multi-Agente (`sdd harness`)** gestiona la orquestación de tareas:
1. **Optimización de Context Window**: Extrae payloads mínimos de tareas para prevenir la sobrecarga de contexto.
2. **Roles Multi-Agente**: El Leader despacha tareas al Worker (implementador) y al QA Reviewer (validador).
3. **Bucle de Auto-Corrección**: Corrige automáticamente fallos de QA hasta un máximo de 3 reintentos.
