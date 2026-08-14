# Devscripts — Monorepo de Automatización y Orquestación

Monorepo desacoplado y estructurado según principios de **Clean Architecture**, **SOLID**, **DDD**, **DRY** y **YAGNI**, dividido en dos subproyectos autónomos y un catálogo global de reglas agnósticas de desarrollo:

```
devscripts/
├── rules/                  # Catálogo de 5 Reglas Globales Agnósticas de Desarrollo
│   ├── 01-buenas-practicas-codigo.md
│   ├── 02-git-workflow-commits.md
│   ├── 03-seguridad-privacidad.md
│   ├── 04-bases-de-datos-migraciones.md
│   └── 05-observabilidad-errores.md
├── packages/
│   ├── workspace/          # Subproyecto 1: Gestor Determinista de Workspaces (Cero IA)
│   │   ├── src/workspace_engine/
│   │   ├── tests/
│   │   ├── templates/
│   │   ├── pyproject.toml
│   │   └── README.md
│   └── sdd/                # Subproyecto 2: Motor Full IA & Gobernanza SDD
│       ├── src/sdd_engine/
│       ├── tests/
│       ├── templates/
│       ├── skills/
│       ├── pyproject.toml
│       └── README.md
├── install.py              # Instalador interactivo multi-agente y setup de paquetes
├── pyproject.toml          # Orquestador del monorepo
└── README.md               # Documentación maestra en español
```

---

## 📦 1. Subproyectos del Monorepo

### 🛠️ `packages/workspace/` — Gestor Determinista (Python Puro, Cero IA)
Herramienta de precisión para gestión de repositorios, entornos y ejecución local sin alucinaciones:
- **Workspaces & Git Worktrees**: `generate-workspace`, `edit-workspace`, `create-worktree`, `clean-workspace`, `reset-repos`, `stop-workspace`, `delete-workspaces`.
- **Entorno y Build**: `build-project`, `install-deps`, `set-java`, `init-env`, `load-env`, `unit-test-benchmark`.
- **Orquestador Local**: `run-local` (descubrimiento de microservicios, mapeo de puertos 8000-8999, reescritura de URLs de clientes, extracción de credenciales de BD y monitor TUI).
- **Kubernetes**: `kube-env` (extracción de variables `.env`, logs y shells interactivos).

### 🤖 `packages/sdd/` — Motor Full IA y Gobernanza SDD
Arnés de orquestación y gobernanza para agentes de IA (Worker + QA Reviewer):
- **Ciclo de Vida Estricto (8 Fases)**: `/sdd-specify` ➔ `/sdd-clarify` ➔ `/sdd-plan` ➔ `/sdd-checklist` ➔ `/sdd-tasks` ➔ `/sdd-analyze` ➔ `/sdd-exec` ➔ `/sdd-converge` (o `sdd quick` para fixes rápidos).
- **Intercepción de Seguridad**: Hooks de pre-herramienta (`sdd hook pre-tool`) para bloqueo de comandos destructivos y post-herramienta (`sdd hook post-tool`) para validación inmediata.
- **Sinergia Determinista**: SDD conoce e invoca las herramientas deterministas de `workspace_engine` para compilar, probar y verificar con certeza técnica y ahorro masivo de tokens.
- **Adaptadores Multi-IA**: Configuración nativa para Google Antigravity (AGY), Claude Code, Cursor IDE, Windsurf, GitHub Copilot, Gemini CLI y ChatGPT.

---

## 📋 2. Catálogo de Reglas Globales Agnósticas (`rules/`)

Catálogo de estándares aplicable a cualquier agente y proyecto:
1. `01-buenas-practicas-codigo.md`: Principios SOLID, límites de tamaño, inmutabilidad y estándares de calidad.
2. `02-git-workflow-commits.md`: Conventional Commits obligatorios en inglés imperativo y **CERO menciones de IA** ni emojis de robot.
3. `03-seguridad-privacidad.md`: Cero secretos hardcodeados y cero PII en logs.
4. `04-bases-de-datos-migraciones.md`: Protocolo estricto de backup previo ("OK WRITE"), migraciones idempotentes (Mongock/Flyway).
5. `05-observabilidad-errores.md`: Logs estructurados, correlación (`X-Trace-Id`) y manejo robusto de excepciones.

---

## ⚡ 3. Instalación Rápida

Ejecutá el instalador interactivo por consola:

```bash
python3 install.py
```

El instalador te permitirá:
1. Seleccionar interactivamente para qué agentes de IA desplegar las reglas globales (`AGENTS.md`, `.gemini/GEMINI.md`, `CLAUDE.md`, `.cursorrules`, `.windsurfrules`).
2. Instalar ambos paquetes (`workspace-engine` y `sdd-engine`) en modo editable (`pip install -e`).

---

## 🧪 4. Ejecución de Tests

```bash
pytest
```
Ambos paquetes cuentan con una suite de pruebas unitarias al 100% de pasaje.
