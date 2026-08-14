# Arquitectura del Monorepo Devscripts

Este documento describe la estructura arquitectónica del monorepo `devscripts`, aplicando principios de **Clean Architecture**, **SOLID**, **Domain-Driven Design (DDD)**, **DRY** y **YAGNI**.

---

## 🏛️ 1. Desacoplamiento y Cero Dependencias Cruzadas

El monorepo está estrictamente dividido en dos subproyectos autónomos y un catálogo de reglas globales:

```
devscripts/
├── rules/                  # Catálogo de Reglas Modulares de Ingeniería (Globales y Scoped)
├── packages/
│   ├── workspace/          # Subproyecto 1: Gestor Determinista de Workspaces (Python Puro, Cero IA)
│   └── sdd/                # Subproyecto 2: Motor Full IA & Gobernanza SDD
├── docs/                   # Documentación transversal con enlaces directos (DRY)
├── install.py              # Instalador interactivo
├── uninstall.py            # Desinstalador interactivo determinista
└── pyproject.toml          # Orquestador del monorepo
```

### Principios Fundamentales:
1. **Aislamiento**: Cada paquete contiene sus propias utilidades privadas (`utils.py`) sin depender de un paquete "core" compartido para evitar el acoplamiento implícito.
2. **Sinergia Determinista**: `packages/sdd/` conoce e invoca las utilidades deterministas de `packages/workspace/` (ej: compilación y testing) de forma segura mediante fallbacks limpios.
3. **Fuente Única de Verdad (DRY)**: Las reglas de desarrollo residen exclusivamente en `rules/` y se compilan a los formatos nativos de cada agente (`.mdc`, `CLAUDE.md`, `AGENTS.md`, `.gemini/GEMINI.md`).
