# Referencia de comandos

- `./install.sh`: instala los paquetes en modo editable y valida entrypoints.
- `spec agent install agents --yes`: instala instrucciones y skills compartidas.
- `spec agent install claude --yes`: agrega el puente de descubrimiento de Claude.
- `spec agent install codex --yes`: instala también las skills de Codex.
- `spec agent install antigravity --yes`: instala también las skills de Antigravity.
- `rules install --local --all`: instala reglas de ingeniería.
- `progress list --json`: muestra tareas compactas.
- `ws worktree <repo> <destino> <rama>`: crea un worktree aislado.
- `ws hooks run`: ejecuta el quality gate local con salida de comandos sólo ante fallos.
- `ws hooks run --output verbose`: transmite la salida completa de todos los comandos.

El hook usa `QG_OUTPUT=errors` de forma predeterminada: conserva el resumen de
las cinco etapas, oculta la salida de comandos exitosos y muestra el diagnóstico
del comando que falla. `QG_OUTPUT=verbose git push` restaura el streaming
completo. Los fallos extensos dejan su transcript completo en
`.git/specops/quality-gate/latest.log`.

Jira y Confluence requieren `ATLASSIAN_URL`, `ATLASSIAN_EMAIL` y
`ATLASSIAN_API_TOKEN`.
