# Toolkit Devscripts & Motor SDD (Spec-Driven Development)

**La Fuente Única de Verdad** para Spec-Driven Development (SDD), orquestación de habilidades de Inteligencia Artificial para Antigravity / Gemini / Claude, aislamiento de workspaces multirrepositorio y directrices de calidad de ingeniería.

---

## 🌟 Capacidades Principales

- **CLI `sdd` & Motor de 8 Fases**: Alineado con la especificación Spec-Kit (`specify`, `clarify`, `plan`, `checklist`, `tasks`, `analyze`, `exec`, `converge`).
- **Catálogo de 16 Habilidades SDD Nativas**: Comandos Slash `/sdd-*` compatibles con Google Antigravity IDE, `agy` CLI, Gemini CLI y Claude Code.
- **Validación Estricta de Parámetros**: Precondiciones obligatorias en todas las habilidades (Paso 0) para evitar ejecuciones con nombres de característica en blanco o caídas en `"default"`.
- **Sincronizador Global Multi-IA (`sdd sync`)**: Propagación atómica de habilidades y reglas hacia `~/.gemini/config/skills/`, `~/.agents/skills/` y adaptadores locales (`.agents/`, `.claude/`, `.github/`).
- **Gestión de Workspaces Multirrepositorio**: Creación, actualización y sincronización de entorno (`generate-workspace`, `create-worktree`, `sync-toolkit`, `toolkit-menu`, `update-toolkit`).
- **Arquitectura Multiplataforma**: 100% Python nativo sin scripts shell obsoletos. Funciona de forma transparente en Windows, macOS y Linux.

---

## 🛠️ Catálogo Completo de las 16 Habilidades SDD (Comandos Slash)

| Comando Slash | Fase / Función | Descripción |
| :--- | :--- | :--- |
| `/sdd-specify` | **Fase 1** | Genera la especificación funcional inicial (`spec.md`) con historias de usuario y Gherkin. |
| `/sdd-clarify` | **Fase 2** | Audita y resuelve ambigüedades, supuestos y vacíos de requerimientos (`clarify.md`). |
| `/sdd-plan` | **Fase 3** | Blueprint técnico, contratos de datos (Zod/DTOs) y diagramas Mermaid (`plan.md`). |
| `/sdd-checklist` | **Fase 4** | Establece las Quality Gates y Definition of Done (`checklist.md`). |
| `/sdd-tasks` | **Fase 5** | Desglose atómico de tareas ejecutables (`tasks.md`). |
| `/sdd-analyze` | **Fase 6** | Auditoría estática cruzada de consistencia entre todos los artefactos. |
| `/sdd-exec` | **Fase 7** | Orquestación iterativa de tareas con roles de Agente Worker y Agente QA Reviewer. |
| `/sdd-converge` | **Fase 8** | Verificación de convergencia verde (suite de tests, checklist y escenarios Gherkin). |
| `/sdd-init` | **Soporte** | Inicialización del espacio SDD con protocolo híbrido (CLI + Inspección Dinámica IA). |
| `/sdd-verify` | **Soporte** | Suite de verificaciones automáticas (linters, unit tests, lecturas GET post-mutación, PII). |
| `/sdd-harness` | **Soporte** | Control de presupuesto de pasos y evaluación de deriva de alcance (*Scope Drift*). |
| `/sdd-quick` | **Hotfix** | Ruta acelerada para parches menores, bugs o refactorizaciones pequeñas. |
| `/sdd-constitution` | **Arquitectura** | Establece o actualiza la fuente de verdad arquitectónica en `.specify/constitution/`. |
| `/sdd-audit` | **Deuda Técnica** | Audita repositorios para catalogar deuda técnica en `.specify/tech-debt.md`. |
| `/sdd-doc` | **Documentación** | Motor autónomo de documentación recursiva, purga de PII y READMEs. |
| `/sdd-remove` | **Mantenimiento** | Respaldado automático `.specify-backup-*` y remoción limpia de adaptadores SDD. |

> Consulte el **[Manual Funcional de Habilidades SDD](docs/sdd-skills.md)** para conocer parámetros, flags y ejemplos detallados.

---

## 🚀 Instalación y Sincronización Global

### Requisitos Previos

- **Sistema Operativo**: macOS, Linux o Windows
- **Python**: 3.10 o superior
- **Git**: 2.30+

### Paso a Paso

1. **Clonar e Instalar en Modo Editable**:
   ```bash
   git clone https://github.com/Ezuser/devscripts.git
   cd devscripts
   pip install -e .
   ```

2. **Sincronizar Habilidades Globales y Adaptadores Multi-IA**:
   Ejecutá `sdd sync` para re-instalar el paquete globalmente y sincronizar todas las 16 habilidades en `~/.gemini/config/skills/`, `~/.agents/skills/` y en el workspace actual:
   ```bash
   python3 -m devscripts.cli.sdd.sdd sync
   ```

3. **Inicializar SDD en un Proyecto**:
   ```bash
   python3 -m devscripts.cli.sdd.sdd init
   ```

---

## ⚙️ Regla de Validación de Parámetros (Paso 0)

Todas las habilidades SDD incorporan una validación de precondiciones en tiempo de ejecución:
- **Prioridad 1**: Utiliza el argumento posicional provisto en la llamada Slash (ej. `/sdd-specify mi-feature`).
- **Prioridad 2**: Si no hay argumento, lee el feature activo en `.specify/feature.json` mediante `sdd feature get`.
- **Modo Estricto**: Si **no se provee argumento** ni **existe feature activo**, la habilidad detiene la ejecución y solicita interactivamente el nombre mediante `AskUserQuestion`, rechazando explícitamente nombres en blanco o valores por defecto "default".

---

## 📚 Documentación Técnica Detallada ([`docs/`](docs/))

- **[Arquitectura SDD y Adaptadores Multi-IA](docs/sdd-architecture.md)** — Justificación de diseño (Por qué), mecanismo (Cómo) y diagramas Mermaid.
- **[Manual Funcional de Habilidades SDD](docs/sdd-skills.md)** — Catálogo completo de las 16 habilidades, entradas, artefactos y ejemplos.
- **[Estructura de Especificación](.specify/README.md)** — Visión general de los artefactos `.specify/`.
- **[Ciclo de Vida de Workspaces](docs/run-workspace.md)** — Creación, actualización y aislamiento multirrepositorio.
- **[Versionado y Releases](docs/versioning.md)** — Versionado automatizado con Release Please.

---

## 🧪 Pruebas y Aseguramiento de Calidad

Ejecutá la suite completa de `pytest` para verificar la integridad del toolkit:

```bash
pytest
```
