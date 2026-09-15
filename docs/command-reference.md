# Referencia de comandos

- `ia-spec-ops-engine install --components governance,spec --yes`: confirma
  componentes disponibles.
- `spec agent install agents|claude`: instala instrucciones y skills.
- `rules install --local --all`: instala reglas de ingeniería.
- `progress list --json`: muestra tareas compactas.
- `ws worktree <repo> <destino> <rama>`: crea un worktree aislado.
- `ws hooks run`: ejecuta el quality gate local.

Jira y Confluence requieren `ATLASSIAN_URL`, `ATLASSIAN_EMAIL` y
`ATLASSIAN_API_TOKEN`.
