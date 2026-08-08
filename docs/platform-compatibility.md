# Compatibilidad de Plataforma & Sandbox

El toolkit `sdd` es compatible de forma nativa con **macOS**, **Linux** y **Windows (vía WSL2)**.

---

## Requisitos de Sistema

- **Bash 3.2+** / **Python 3.8+**
- **Git 2.20+** (Requerido para soporte de Worktrees).
- **Docker Engine / Desktop** (Opcional, para ejecución de runners sandboxed).

---

## Soporte por Plataforma

| Sistema Operativo | Compatibilidad | Notas |
| :--- | :--- | :--- |
| **macOS** | ✅ Nativo | Funciona en Zsh y Bash. |
| **Linux (Ubuntu/Debian/Arch)** | ✅ Nativo | Se recomienda Docker Engine nativo. |
| **Windows** | ✅ WSL2 | Debe ejecutarse dentro del sistema de archivos de WSL (`~/`). |
