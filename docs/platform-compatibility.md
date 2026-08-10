# Platform Compatibility & Sandbox

The `devscripts` toolkit features a **100% Python cross-platform architecture** (0% `.sh`, 0% `.bat`, 0% `.bats`), ensuring it works natively across all major operating systems.

---

## System Requirements

- **Python 3.10+**
- **Git 2.20+** (Required for Worktree support).
- **Docker Engine / Docker Desktop** (Optional, for sandboxed runner execution).

---

## Platform Support

| Operating System | Compatibility | Notes |
| :--- | :--- | :--- |
| **macOS** | ✅ Native | Full support. |
| **Linux (Ubuntu/Debian/Arch)** | ✅ Native | Full support. Docker Engine recommended for sandboxing. |
| **Windows** | ✅ Native | Native execution via Python. No WSL2 dependency required. |

## Installation & Entrypoints

The toolkit uses binary installation and registers entrypoints via `pyproject.toml` `console_scripts`. 

Available commands include:
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

## Execution Modes

All CLI scripts support a **Dual execution mode**:
1. **Interactive TUI mode**: Rich terminal user interface for guided operations.
2. **CLI flags**: Full command-line interface with `--help` documentation for headless or automated execution.

## SDD Engine

Fully aligned with the Spec-Kit 8-phase SDD engine:
1. **specify**: Functional specification.
2. **clarify**: Ambiguity resolution.
3. **plan**: Technical blueprint.
4. **checklist**: Quality gates.
5. **tasks**: Executable task breakdown.
6. **analyze**: Static consistency audit.
7. **exec**: Iterative execution.
8. **converge**: Final verification.
*(Includes `quick` for minor patches).*

## AI Agent Adaptation Matrix

Dynamic End-to-End AI Agent adaptation matrix supporting:
- Antigravity 2.0
- Gemini CLI
- Claude Code
- GitHub Copilot
- Cursor
- ChatGPT
