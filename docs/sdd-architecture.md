# Arquitectura SDD & Adaptadores Multi-IA

El motor de **Spec-Driven Development (SDD)** del toolkit opera sobre artefactos Markdown estándar dentro de `.specify/`:

- `.specify/constitution/`: Principios de arquitectura y reglas del proyecto.
- `.specify/specs/`: Especificaciones y planes (`spec.md`, `plan.md`, `tasks.md`).
- `.specify/memory.md`: Memoria histórica acumulativa para evitar regresiones.
- `.specify/tech-debt.md`: Inventario de deuda técnica detectada.

---

## Adaptadores Multi-IA (`templates/agents/sdd-bridge.sh`)

El toolkit es **100% agnóstico al agente o modelo de IA** utilizado. Ejecutando `templates/agents/sdd-bridge.sh` se inyectan automáticamente las instrucciones adaptadas para:

- **Google Antigravity 2.0 (AGY)**: `AGENTS.md` (instrucciones en la raíz) + `.agents/skills/` (skills modulares) + `.agents/rules/` (reglas del proyecto).
- **Claude Code**: `CLAUDE.md` e integración de skills.
- **GitHub Copilot**: `.github/copilot-instructions.md`.
- **Cursor**: `.cursorrules` y `.cursor/rules/`.
- **Gemini CLI**: `.gemini/GEMINI.md`.
- **ChatGPT / Custom GPTs**: `CHATGPT.md`.
