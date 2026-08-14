# workspace_engine — Gestor Determinista de Workspaces y Microservicios

Subproyecto autónomo de automatización y gestión de entornos de desarrollo, Git worktrees, dependencias, compilación y orquestación local para microservicios.

## 🚀 Características Principales

1. **Gestión de Workspaces y Worktrees**:
   - `generate-workspace`: Creación determinista de workspaces multi-repositorio a partir de Git worktrees.
   - `edit-workspace`: Adición y remoción interactiva de repositorios en un workspace activo.
   - `create-worktree`: Creación rápida de worktrees aislados para ramas de desarrollo.
   - `clean-workspace`: Limpieza profunda de artefactos de compilación (`node_modules`, `.gradle`, `build/`, `dist/`).
   - `reset-repos`: Reseteo de repositorios al commit base o HEAD limpio.
   - `stop-workspace`: Detención segura de procesos y servicios levantados en background.
   - `delete-workspaces`: Eliminación de workspaces y desregistro de worktrees.

2. **Entorno de Ejecución y Herramientas**:
   - `build-project`: Compilación multi-stack (Gradle, Maven, Node, Go, Python).
   - `install-deps`: Instalación determinista de dependencias de host.
   - `set-java`: Detección automática de versión requerida de JDK y configuración vía SDKMAN.
   - `init-env` / `load-env`: Sincronización de archivos `.env` interactiva a partir de plantillas `.env.example`.
   - `unit-test-benchmark`: Ejecución paralela de suites de tests unitarios y reporte visual de métricas.

3. **Orquestador Local (`run-local`)**:
   - Descubrimiento automático de servicios y asignación determinista de puertos locales (rango 8000–8999).
   - Re-escritura automática de URLs remotas a puertos locales (`wire_urls`).
   - Extracción y mapeo de credenciales de bases de datos (MongoDB, PostgreSQL).
   - Monitor interactivo TUI con soporte para logs en tiempo real, reinicio en cascada y apertura de navegadores/Swagger.

4. **Gestión de Kubernetes (`kube-env`)**:
   - TUI interactiva para extracción de variables de pods Kubernetes (`.env`, `set-env.sh`), streaming de logs (con soporte Stern/Tmux) y apertura de shells.

## 📦 Instalación

```bash
cd packages/workspace
pip install -e .
```

## 🛠️ Comandos de Consola Disponibles

| Comando | Descripción |
|---|---|
| `generate-workspace` | Genera un nuevo workspace multi-repo |
| `edit-workspace` | Edita repositorios en el workspace actual |
| `create-worktree` | Crea un worktree para una rama |
| `clean-workspace` | Limpia caches y artefactos de compilación |
| `stop-workspace` | Detiene servicios corriendo en el workspace |
| `reset-repos` | Resetea repositorios al commit origen |
| `delete-workspaces` | Elimina workspaces y limpia worktrees |
| `build-project` | Compila proyectos Maven/Gradle/Node/Go |
| `install-deps` | Instala dependencias locales de repositorios |
| `set-java` | Configura el entorno Java JDK adecuado |
| `init-env` | Inicializa variables `.env` interactivamente |
| `unit-test-benchmark` | Ejecuta benchmark de tests con reporte visual |
| `run-local` | Orquesta y levanta microservicios localmente |
| `kube-env` | TUI de gestión e inspección de pods Kubernetes |
