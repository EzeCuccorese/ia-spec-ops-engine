# Devscripts — Monorepo de Automatización y Orquestación

Monorepo desacoplado y estructurado según principios de **Clean Architecture**, **SOLID**, **DDD**, **DRY** y **YAGNI**, dividido en tres subproyectos autónomos y un catálogo global de reglas agnósticas de desarrollo:

```
devscripts/
├── rules/                  # Catálogo de Reglas Modulares de Desarrollo (Globales y Scoped)
│   ├── global/             # Reglas universales inyectadas siempre (anti-looping, commits, seguridad, SDD)
│   └── scoped/             # Reglas por stack técnico (Java, Python, TypeScript, React, Go, Rust, DevOps, etc.)
├── packages/
│   ├── common/             # Subproyecto 0: Base compartida, tipado, subprocess determinista y parsers
│   │   ├── src/devscripts_common/
│   │   └── tests/
│   ├── workspace/          # Subproyecto 1: Gestor Determinista de Workspaces (CLI unificado `ws`, Cero IA)
│   │   ├── src/workspace_engine/
│   │   ├── tests/
│   │   ├── templates/
│   │   └── pyproject.toml
│   └── sdd/                # Subproyecto 2: Motor Full IA & Gobernanza SDD (CLI `sdd`)
│       ├── src/sdd_engine/
│       ├── tests/
│       ├── templates/
│       ├── skills/
│       └── pyproject.toml
├── install.py              # Instalador interactivo multi-agente y setup de paquetes (soporte uv / pip)
├── uninstall.py            # Desinstalador dinámico quirúrgico y limpiador de agentes
├── pyproject.toml          # Orquestador del monorepo
└── README.md               # Documentación maestra en español
```

---

## 📦 1. Subproyectos del Monorepo

### 🧩 `packages/common/` — Base Compartida (`devscripts_common`)
- Utilidades unificadas de consola (Rich / ANSI).
- Parser determinista de variables de entorno `.env` y `set-env.sh`.
- Parser centralizado de YAML frontmatter para reglas y especificaciones.
- Wrappers seguros de subprocess con timeouts obligatorios para prevenir bloqueos de red.
- Detección de proyectos (Spring Boot, Node, Go, Rust, Gradle, Maven, Python).

### 🛠️ `packages/workspace/` — Gestor Determinista (CLI `ws`)
Herramienta de precisión para gestión de repositorios, entornos y ejecución local sin alucinaciones:
- **CLI Unificado `ws`**:
  - `ws generate`: Crea un workspace con Git worktrees aislados.
  - `ws edit`: Agrega o modifica repositorios dentro de un workspace.
  - `ws worktree`: Genera un worktree git atómico.
  - `ws clean`: Limpia artefactos de compilación y caches.
  - `ws stop`: Detiene todos los procesos del workspace.
  - `ws reset`: Resetea repositorios al estado de upstream.
  - `ws delete`: Elimina workspaces y limpia los worktrees asociados.
  - `ws build` / `ws deps` / `ws java`: Compila e instala dependencias detectando el runtime.
  - `ws env-init` / `ws env-load`: Inicializa y carga variables de entorno.
  - `ws run-local`: Orquestador local con monitor TUI interactivo.
  - `ws kube`: Gestor de Kubernetes para extracción de entornos con permisos `chmod 600`.
  - `ws doctor`: Diagnóstico de herramientas instaladas en el sistema.

### 🤖 `packages/sdd/` — Motor Full IA y Gobernanza SDD (CLI `sdd`)
Arnés de orquestación y gobernanza para agentes de IA (Worker + QA Reviewer):
- **Ciclo de Vida Estricto (8 Fases)**: `/sdd-specify` ➔ `/sdd-clarify` ➔ `/sdd-plan` ➔ `/sdd-checklist` ➔ `/sdd-tasks` ➔ `/sdd-analyze` ➔ `/sdd-exec` ➔ `/sdd-converge` (o `sdd quick` para fixes rápidos).
- **Intercepción de Seguridad**: Hooks de pre-herramienta (`sdd hook pre-tool`) para bloqueo de comandos destructivos y post-herramienta (`sdd hook post-tool`) para validación inmediata.
- **Sinergia Determinista**: SDD conoce e invoca las herramientas deterministas de `workspace_engine` para compilar, probar y verificar con certeza técnica y ahorro masivo de tokens.
- **Adaptadores Multi-IA**: Configuración nativa para Google Antigravity (AGY), Claude Code, Cursor IDE, Windsurf, GitHub Copilot, Gemini CLI y ChatGPT.

---

## 📋 2. Catálogo de Reglas Modulares (`rules/`)

Catálogo de estándares aplicable a cualquier agente y proyecto:
- **Globales**: Guardrails anti-looping, Conventional Commits en inglés imperativo (**CERO menciones de IA**), cero secretos y ciclo de vida SDD.
- **Scoped**: Reglas especializadas activadas por `globs` para Java/Spring, Python Async/FastAPI, Node.js Backend, React Moderno, Go, Rust, DevOps/Containers, Migraciones de BD, Contratos API, Observabilidad y Caching/Brokers.

---

## ⚡ 3. Instalación Rápida

Ejecutá el instalador interactivo por consola:

```bash
python3 install.py
```

El instalador detecta si `uv` está disponible para una instalación ultrarrápida (con fallback a `pip`) y despliega las reglas en los agentes seleccionados.

Para desinstalar y limpiar el entorno:

```bash
python3 uninstall.py
```

---

## 🧪 4. Ejecución de Tests

```bash
pytest
```
