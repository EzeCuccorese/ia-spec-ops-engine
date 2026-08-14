# sdd_engine — Motor de IA y Gobernanza para Spec-Driven Development (SDD)

Subproyecto autónomo de orquestación, gobernanza, harness multi-agente y verificación automática para desarrollo guiado por especificaciones (Spec-Driven Development).

## 🚀 Ciclo de Vida Estricto de 8 Fases

1. `sdd specify`: Fase 1 — Especificación funcional (`spec.md`).
2. `sdd clarify`: Fase 2 — Resolución de ambigüedades y quality gates (`clarify.md`).
3. `sdd plan`: Fase 3 — Blueprint técnico y contratos formales de datos (`plan.md`).
4. `sdd checklist`: Fase 4 — Quality gates y Definition of Done (`checklist.md`).
5. `sdd tasks`: Fase 5 — Desglose atomizado de tareas ejecutables (`tasks.md`).
6. `sdd analyze`: Fase 6 — Auditoría estática cruzada entre artefactos.
7. `sdd exec`: Fase 7 — Ejecución iterativa de tareas con Agente Worker y Agente QA Reviewer.
8. `sdd converge`: Fase 8 — Verificación final de convergencia y criterios de aceptación Gherkin.

*Para correcciones rápidas de bugs o parches pequeños, usar `sdd quick`.*

## 🛡️ Pilares y Gobernanza

- **Contratos Primero**: Definir interfaces formales antes de la lógica de negocio.
- **Harnés de Pruebas (Test-First)**: Pruebas unitarias e integración previas al código productivo.
- **Implementación Mínima**: Código estrictamente necesario para cumplir el contrato (YAGNI).
- **Detección Temprana & Intercepción de Seguridad**:
  - `sdd hook pre-tool`: Bloqueo de comandos destructivos, ejecución remota no autorizada (`curl|sh`), borrado de raíz o mutaciones directas de BD sin autorización.
  - `sdd hook post-tool`: Verificación automática instantánea (linter, tests, escaneo de secretos/PII, confirmación GET).
- **Adaptadores Multi-IA**: Despliegue nativo de prompts, skills y configuraciones para Claude Code, Antigravity 2.0 (AGY), GitHub Copilot, Cursor IDE, Windsurf, Gemini CLI y ChatGPT.

## 📦 Instalación

```bash
cd packages/sdd
pip install -e .
```

## 🛠️ Comandos CLI Disponibles

| Comando | Descripción |
|---|---|
| `sdd init` | Inicializa el espacio de trabajo SDD y adaptadores de IA |
| `sdd feature set <name>` | Establece o cambia la feature activa con aislamiento de worktree |
| `sdd feature status` | Muestra el estado y fase de la feature activa |
| `sdd specify` / `sdd plan` | Asiste en las fases del ciclo de vida SDD |
| `sdd verify` | Ejecuta verificación de linter, tests, secretos y confirmaciones |
| `sdd analyze` | Audita consistencia estática cruzada de artefactos |
| `sdd harness run` | Orquesta ejecución de tareas con Worker y QA Reviewer |
| `sdd finish` | Finaliza feature, sube rama y crea PR |
| `sdd sync` | Sincroniza adaptadores de IA y skills en el repositorio |
| `sdd revoke` | Revoca y limpia configuraciones de SDD en el proyecto |
