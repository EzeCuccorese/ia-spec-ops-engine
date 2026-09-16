# Agentes de código

`AGENTS.md` es la única fuente compartida para Codex, Cursor, Antigravity,
Windsurf, Aider, Copilot, Gemini y agentes compatibles.

```bash
spec init --root .
spec agent install agents --root . --yes
```

Claude conserva la misma fuente y agrega solamente un puente reversible:

```bash
spec agent install claude --root . --yes
```

Esto crea `AGENTS.md` y un `CLAUDE.md` con `@AGENTS.md`; las skills se instalan
en `.claude/skills/`. La desinstalación valida propiedad y conserva texto propio.

`rules install --local --all` administra sólo el bloque de reglas dentro de
`AGENTS.md`. `spec agent` administra su propio bloque y los puentes de proveedor;
ambos preservan los bloques ajenos. `rules --agent claude/cursor` ya no se admite.
En instalaciones antiguas, conservá los archivos del proveedor y migrá cualquier
regla propia antes de retirar manualmente su bloque `<!-- rules:start -->`.
