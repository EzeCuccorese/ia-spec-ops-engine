# Documentación de Devscripts

Bienvenido a la documentación central de **Devscripts**. 

Este espacio sigue el principio de **Fuente Única de Verdad (DRY)**: los manuales operativos y guías de comandos residen directamente en sus respectivos subproyectos y catálogos para evitar duplicaciones.

---

## 🧭 Índice de Navegación

### 📦 1. Subproyectos Autónomos
- [**Workspace Engine (`packages/workspace/`)**](file://~/projects/devscripts/packages/workspace/README.md): Gestor determinista en Python puro (cero IA) para repositorios, Git worktrees, compilación multi-stack, gestión de JDKs, orquestador de microservicios (`run-local`) y Kubernetes (`kube-env`).
- [**SDD Engine (`packages/sdd/`)**](file://~/projects/devscripts/packages/sdd/README.md): Motor Full IA y arnés de gobernanza para agentes de IA (Worker + QA Reviewer), ciclo de vida estricto de 8 fases, hooks de seguridad y adaptadores Multi-IA.

---

### 📋 2. Catálogo de Reglas de Ingeniería
- [**Catálogo de Reglas Modulares (`rules/`)**](file://~/projects/devscripts/rules/README.md):
  - **Reglas Globales (`rules/global/`)**: Interacción y anti-looping, Conventional Commits y Cero IA mentions, seguridad/privacidad y ciclo SDD.
  - **Reglas Scoped (`rules/scoped/`)**: Java/Spring, Python, TypeScript/Frontend, React Moderno, Go, Rust, DevOps/K8s, Testing, Bases de Datos, APIs y Observabilidad.

---

### 🏛️ 3. Arquitectura y Metodología
- [**Ciclo de Vida SDD Paso a Paso**](file://~/projects/devscripts/docs/sdd/lifecycle.md): Detalle metodológico de las 8 fases canónicas con diagramas Mermaid.
- [**Referencia de Habilidades SDD**](file://~/projects/devscripts/docs/sdd/skills-reference.md): Catálogo de las 14 skills canónicas y roles multi-agente.
- [**Arquitectura Multi-Agente SDD**](file://~/projects/devscripts/docs/sdd/architecture.md): Células especializadas, invariantes de ejecución y Spec-Kit.
- [**Arquitectura del Monorepo**](file://~/projects/devscripts/docs/architecture/monorepo.md): Principios SOLID, DDD, DRY, YAGNI y desacoplamiento de paquetes.

---

## ⚡ Instalación y Desinstalación Rápida
- **Instalación**: [`python3 install.py`](file://~/projects/devscripts/install.py) (Menú interactivo de selección de agentes y setup pip en modo editable).
- **Desinstalación**: [`python3 uninstall.py`](file://~/projects/devscripts/uninstall.py) (Limpieza quirúrgica y desinstalación determinista).
