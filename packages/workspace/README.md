# workspace_engine — Gestor Determinista de Workspaces y Microservicios

Subproyecto autónomo de automatización y gestión de entornos de desarrollo, Git worktrees, dependencias, compilación y orquestación local para microservicios.

## 🚀 Características Principales

1. **Gestión de Workspaces y Worktrees**:
   - `ws generate`: Creación determinista de workspaces multi-repositorio a partir de Git worktrees.
   - `ws edit`: Adición y remoción interactiva de repositorios en un workspace activo.
   - `ws worktree`: Creación rápida de worktrees aislados para ramas de desarrollo.
   - `ws clean`: Limpieza profunda de artefactos de compilación (`node_modules`, `.gradle`, `build/`, `dist/`).
   - `ws reset`: Reseteo de repositorios al commit base o HEAD limpio.
   - `ws stop`: Detención segura de procesos y servicios levantados en background.
   - `ws delete`: Eliminación de workspaces y desregistro de worktrees.

2. **Gestión de Git Hooks & Quality Gate (`ws hooks`)**:
   - `ws hooks status`: Diagnóstico visual del estado de hooks locales y globales.
   - `ws hooks install [--global]`: Instalación y configuración de Quality Gate de 4 etapas (Seguridad de secretos, Políticas Git/Cero IA, Linters multi-stack y Tests).
   - `ws hooks uninstall [--global]`: Desinstalación y desvinculación limpia de hooks.
   - *Ver guía detallada en [docs/workspace/git-hooks.md](../../docs/workspace/git-hooks.md)*.

3. **Entorno de Ejecución y Herramientas**:
   - `ws build`: Compilación multi-stack (Gradle, Maven, Node, Go, Python).
   - `ws deps`: Instalación determinista de dependencias de host.
   - `ws java`: Detección automática de versión requerida de JDK y configuración vía SDKMAN.
   - `ws env-init` / `ws env-load`: Sincronización de archivos `.env` interactiva a partir de plantillas `.env.example`.
   - `ws benchmark`: Ejecución paralela de suites de tests unitarios y reporte visual de métricas.

4. **Orquestador Local (`ws run-local`)**:
   - Descubrimiento automático de servicios y asignación determinista de puertos locales (rango 8000–8999).
   - Re-escritura automática de URLs remotas a puertos locales (`wire_urls`).
   - Extracción y mapeo de credenciales de bases de datos (MongoDB, PostgreSQL).
   - Monitor interactivo TUI con soporte para logs en tiempo real, reinicio en cascada y apertura de navegadores/Swagger.

5. **Gestión de Kubernetes (`ws kube`)**:
   - TUI interactiva para extracción de variables de pods Kubernetes (`.env`, `set-env.sh`), streaming de logs (con soporte Stern/Tmux) y apertura de shells.

## 📦 Instalación

```bash
cd packages/workspace
pip install -e .
```

## 🛠️ Comandos CLI Disponibles (`ws`)

| Comando | Descripción |
|---|---|
| `ws hooks` | Gestor de Git Hooks y Quality Gates (`install`, `status`, `uninstall`) |
| `ws generate` | Genera un nuevo workspace multi-repo |
| `ws edit` | Edita repositorios en el workspace actual |
| `ws worktree` | Crea un worktree para una rama |
| `ws clean` | Limpia caches y artefactos de compilación |
| `ws stop` | Detiene servicios corriendo en el workspace |
| `ws reset` | Resetea repositorios al commit origen |
| `ws delete` | Elimina workspaces y limpia worktrees |
| `ws build` | Compila proyectos Maven/Gradle/Node/Go |
| `ws deps` | Instala dependencias locales de repositorios |
| `ws java` | Configura el entorno Java JDK adecuado |
| `ws env-init` | Inicializa variables `.env` interactivamente |
| `ws env-load` | Carga e inspecciona variables de entorno |
| `ws benchmark` | Ejecuta benchmark de tests con reporte visual |
| `ws run-local` | Orquesta y levanta microservicios localmente |
| `ws kube` | TUI de gestión e inspección de pods Kubernetes |
| `ws doctor` | Diagnóstico del entorno de desarrollo y herramientas |
