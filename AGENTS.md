# Google Antigravity (AGY) — Agent System Instructions

# Spec-Driven Development (SDD) — Reglas Centrales y Ciclo de Vida Paso a Paso

## 1. Ciclo de Vida Estricto (Puntos de Control Humano)
El desarrollo de features DEBE avanzar secuencialmente, requiriendo revisión y aprobación humana antes de iniciar cada fase:
1. `/sdd-specify`: Especificación funcional (`spec.md`).
2. `/sdd-clarify`: Resolución de ambigüedades y análisis de riesgos (`clarify.md`).
3. `/sdd-plan`: Blueprint técnico y contratos formales de datos (`plan.md`).
4. `/sdd-checklist`: Quality gates y Definition of Done (`checklist.md`).
5. `/sdd-tasks`: Desglose atomizado de tareas ejecutables (`tasks.md`).
6. `/sdd-analyze`: Auditoría estática cruzada entre artefactos.
7. `/sdd-exec`: Ejecución iterativa de tareas con Agente Worker y Agente QA.
8. `/sdd-converge`: Verificación final de convergencia y criterios de aceptación Gherkin.

*Nota*: Para correcciones rápidas de bugs, usar exclusivamente `sdd quick`.

## 2. Pilares de SDD
- **Contratos Primero**: Definir interfaces TypeScript, esquemas Zod o DTOs Java antes de implementar la lógica.
- **Harnés de Pruebas (Test-First)**: Escribir pruebas unitarias/integración (Rojo) antes de la lógica de negocio.
- **Implementación Mínima**: Escribir el código estrictamente necesario para cumplir el contrato y pasar la prueba (Verde).
- **Detección Temprana**: Ejecutar linters y verificar lecturas de confirmación tras mutaciones.

## 3. Reglas de Git y Seguridad
- **Conventional Commits**: Escribir mensajes de commit en inglés (`type(scope): description`) en minúsculas e imperativo.
- **ZERO AI MENTIONS / CERO MENCIONES DE IA**: Nunca incluir frases como "Generado con IA" ni emojis de robots 🤖 en PRs, commits o comentarios.
- **Seguridad y Privacidad**: Cero secretos hardcodeados. Cero PII guardada en logs.

## 4. Protocolo Híbrido para Habilidades de Agentes (Determinismo + Validación Dinámica de IA)
Al ejecutar cualquier habilidad (ej. `sdd-init`, `sdd-verify`, `sdd-constitution`, `sdd-plan`), el agente DEBE cumplir 3 fases:
1. **Fase 1 (Determinística)**: Ejecutar herramientas CLI / scripts estáticos (`python3 -m devscripts.cli.sdd ...`).
2. **Fase 2 (Auditoría Dinámica de IA)**: Inspeccionar el código fuente del repositorio (manifests, linters, tests, arquitectura y convenciones no escritas).
3. **Fase 3 (Enriquecimiento Explícito)**: Inyectar las reglas y buenas prácticas descubiertas en `.specify/constitution/constitution.md` y `.specify/memory.md` en la sección `## 🔍 Descubrimientos Dinámicos de IA & Buenas Prácticas del Proyecto`.

## Antigravity Agent Flow
- Consult active SDD skills in `.agents/skills/` and `skills/`.
- Progress step-by-step after user sign-off.
