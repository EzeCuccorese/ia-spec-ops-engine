# Compatibilidad de Plataforma y Sandbox

El toolkit `devscripts` cuenta con una **arquitectura multiplataforma 100% Python** (0% `.sh`, 0% `.bat`, 0% `.bats`), lo que garantiza su funcionamiento nativo en todos los sistemas operativos principales.

---

## Requisitos del Sistema

- **Python 3.10+**
- **Git 2.20+** (Requerido para soporte de Git Worktrees).
- **Docker Engine / Docker Desktop** (Opcional, para ejecución contenerizada aislada).

---

## Soporte por Plataforma

| Sistema Operativo | Compatibilidad | Notas |
| :--- | :--- | :--- |
| **macOS** | ✅ Nativo | Soporte completo. |
| **Linux (Ubuntu/Debian/Arch)** | ✅ Nativo | Soporte completo. Se recomienda Docker Engine para sandbox. |
| **Windows** | ✅ Nativo | Ejecución nativa vía Python. No requiere dependencia de WSL2. |

---

## Instalación y Puntos de Entrada

El toolkit utiliza instalación binaria y registra puntos de entrada en `pyproject.toml` vía `console_scripts`.

Comandos disponibles:
- `install`
- `uninstall`
- `sdd`
- `create-worktree`
- `generate-workspace`
- `sync-toolkit`
- `toolkit-menu`
- `update-toolkit`
- `run-local`
- `kube-env`

---

## Modos de Ejecución

1. **Modo TUI Interactivo**: Ejecutar comandos sin argumentos abre una interfaz de usuario rica basada en terminal.
2. **Modo Banderas CLI**: Pasar argumentos y banderas para scripts automatizados e integración continua.
