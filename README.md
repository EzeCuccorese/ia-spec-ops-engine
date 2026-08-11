# Toolkit Devscripts & Motor SDD

**La Fuente Única de Verdad** para Spec-Driven Development (SDD), aislamiento de workspaces multirrepositorio, herramientas para desarrolladores y directrices de calidad de ingeniería.

---

## 🌟 Capacidades Principales

- **CLI `sdd`**: Motor de SDD de 8 fases alineado con la especificación de Spec-Kit (`specify`, `clarify`, `plan`, `checklist`, `tasks`, `analyze`, `exec`, `converge`), gestión del estado del feature y acceso directo simplificado para corrección rápida de bugs (`sdd quick`).
- **Gestión de Workspaces**: Aislamiento multirrepositorio, creación de workspaces, edición y scripts de sincronización (`generate-workspace`, `create-worktree`, `sync-toolkit`, `toolkit-menu`, `update-toolkit`).
- **Utilidades para Desarrolladores**: TUIs interactivas y herramientas CLI para orquestación de servicios locales (`run-local`), compilación multi-stack (`build-project`), gestión del contexto de Kubernetes (`kube-env`), control de VPN (`toggle-vpn`) y dashboards de servicios (`devscripts-dashboard`).
- **Arquitectura Multiplataforma**: 100% Python (0% `.sh`, 0% `.bat`, 0% `.bats`). Funciona de forma nativa en Windows, macOS y Linux.
- **Adaptación Dinámica para IAs**: Matriz de adaptación End-to-End para Agentes de IA compatible con Antigravity 2.0, Gemini CLI, Claude Code, GitHub Copilot, Cursor y ChatGPT.

---

## 🚀 Instalación y Configuración

### Requisitos Previos

- **Sistema Operativo**: Windows, macOS o Linux
- **Dependencias**: `python3` (3.10+ recomendado), `git`

### Paso a Paso de Instalación

1. **Clonar el Repositorio**:
   ```bash
   git clone https://github.com/Ezuser/devscripts.git
   cd devscripts
   ```

2. **Instalar vía pip / pyproject.toml**:
   Este proyecto utiliza una arquitectura multiplataforma 100% Python. Todos los scripts CLI están registrados como puntos de entrada ejecutable en `pyproject.toml`.
   ```bash
   pip install -e .
   ```
   Esto instala todos los comandos (`install`, `uninstall`, `sdd`, `create-worktree`, `generate-workspace`, `sync-toolkit`, `toolkit-menu`, `update-toolkit`, `run-local`, `kube-env`, etc.) directamente en el PATH de tu entorno Python.

3. **Verificar Instalación**:
   ```bash
   sdd --help
   ```

---

## 💻 Modo de Ejecución Dual

TODOS los scripts CLI soportan un modo de ejecución dual:
- **Modo TUI Interactivo**: Ejecutá el comando sin argumentos para abrir una interfaz de terminal interactiva y enriquecida.
- **Modo Banderas CLI**: Ejecutá el comando con banderas y `--help` para automatización y scripts de CI/CD.

---

## ⚙️ Configuración y Setup del Proyecto

1. **Inicializar Estructura SDD en un Repositorio**:
   Navegá a la carpeta de tu proyecto destino y ejecutá:
   ```bash
   sdd init
   ```
   Esto inicializa la estructura de directorios estandarizada [`.specify/`](.specify/README.md) (`.specify/constitution/`, `.specify/specs/`, `.specify/memory.md`, `.specify/tech-debt.md`).

2. **Sincronizar Toolkit y Reglas Agnósticas**:
   Para propagar habilidades y reglas actualizadas desde `devscripts` hacia workspaces activos:
   ```bash
   sync-toolkit
   ```

---

## 🏃 Guía de Inicio Rápido

### 1. Spec-Driven Development (CLI `sdd`)

- **Ciclo de Vida de Desarrollo de Feature Paso a Paso**:
  ```bash
  sdd feature jwt-auth      # Establecer nombre del feature activo
  sdd specify               # Fase 1: Especificación funcional (spec.md)
  sdd clarify               # Fase 2: Resolución de ambigüedades (clarify.md)
  sdd plan                  # Fase 3: Blueprint técnico y contratos (plan.md)
  sdd checklist             # Fase 4: Quality Gates & DoD (checklist.md)
  sdd tasks                 # Fase 5: Desglose de tareas ejecutables (tasks.md)
  sdd analyze               # Fase 6: Auditoría de consistencia entre artefactos
  sdd exec                  # Fase 7: Ejecución de tareas con Agentes Worker y QA
  sdd harness run           # Harness de Ejecución: Orquestación batch multi-agente
  sdd converge              # Fase 8: Validación final y aprobación Gherkin
  ```

- **Shortcut para Corrección Rápida de Bugs**:
  ```bash
  sdd quick "Corregir puntero nulo en la calculadora de pedidos"
  ```

- **Auditar Cumplimiento de SDD en el Workspace**:
  ```bash
  sdd audit
  ```

### 2. Workspaces Multirrepositorio

- **Crear un workspace aislado**:
  ```bash
  generate-workspace
  ```
- **Editar repositorios en el workspace**:
  ```bash
  edit-workspace
  ```
- **Eliminar workspaces de forma segura**:
  ```bash
  delete-workspaces
  ```

### 3. Utilidades Principales para Desarrolladores

- **Dashboard Interactivo de Servicios**: `devscripts-dashboard`
- **Orquestar Servicios Locales**: `run-local`
- **Compilar Proyectos Multi-Stack**: `build-project`
- **TUI del Contexto de Kubernetes**: `kube-env`
- **Alternar Conexión VPN**: `toggle-vpn`

---

## 📜 Reglas de Desarrollo y Estándares de Calidad ([AGENTS.md](AGENTS.md))

Índice central de directrices de calidad, estándares de ingeniería y políticas de seguridad:

- **[Instrucciones del Sistema para Agentes](AGENTS.md)** — Descripción general de la arquitectura y directrices.
- **[Reglas Globales del Proyecto](config/rules-global/README.md)** — Especificaciones de reglas globales aplicadas en todos los repositorios gestionados.

---

## 📚 Documentación Técnica ([`docs/`](docs/README.md))

Guías detalladas sobre arquitectura, contenedores sidecar, especificaciones de base de datos u orquestación de plataformas:

- **[Estructura de Especificación](.specify/README.md)** — Visión general de la estructura de `.specify/` y el flujo de trabajo SDD.
- **[Arquitectura SDD](docs/sdd-architecture.md)** — Diseño técnico del CLI y agentes de Spec-Driven Development.
- **[Ciclo de Vida de Workspaces](docs/run-workspace.md)** — Creación, actualización y sincronización multirrepositorio.
- **[Ejecución en Sandbox Contenerizado](docs/agent-sandbox-startup-flow.md)** — Flujo de arranque de aislamiento contenerizado.
- **[Arquitectura de Contenedores Sidecar](docs/sidecar-architecture.md)** — Arquitectura de contenedores aislados.
- **[Flujo del Sidecar Instalador](docs/installer-sidecar-flow.md)** — Flujo contenerizado de instalación de dependencias.
- **[Flujo del Sidecar de Pruebas](docs/test-runner-sidecar-flow.md)** — Ejecución aislada de entornos de pruebas unitarias.
- **[TUI de Entornos Kubernetes](docs/kube-env.md)** — Guía para gestionar entornos de clústeres Kubernetes.
- **[Caché de Dependencias](docs/dependency-caching.md)** — Estrategia de caché de volúmenes para herramientas de build.
- **[Versionado y Releases](docs/versioning.md)** — Versionado automatizado con Release Please.
- **[Configuración de Windows y Figma](docs/windows-figma-setup.md)** — Instrucciones de configuración para Windows y diseño.

---

## 🧪 Pruebas y Aseguramiento de Calidad

Ejecutá la suite completa de pytest para verificar la integridad del toolkit:

```bash
pytest
```
