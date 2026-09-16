# ia-spec-ops-engine

Herramientas personales para configurar agentes de código, administrar
workspaces y usar Spec-Driven Development desde la terminal.

## Qué incluye

- `ai-governance`: reglas, progreso, telemetría y utilidades Atlassian.
- `spec`: specs, planificación, trazabilidad y evidencia verificable.
- `workspace`: worktrees, quality gates y servicios locales.

`AGENTS.md` es la fuente común de instrucciones. Claude suma un `CLAUDE.md`
mínimo que contiene `@AGENTS.md`, sin duplicar reglas ni borrar contenido personal.

## Instalación

Instalá solo lo que uses:

```bash
uv venv
source .venv/bin/activate
uv pip install -e packages/ai-governance
uv pip install -e packages/spec
uv pip install -e packages/workspace
```

Para instalar los tres paquetes y las herramientas de desarrollo:

```bash
./install.sh
source .venv/bin/activate
```

El instalador crea `.venv` si falta y puede ejecutarse otra vez para actualizarla.
Los wrappers `./bin/specops`, `./bin/spec` y `./bin/ws` usan ese mismo entorno.
La raíz es un checkout de desarrollo; los paquetes instalables viven en `packages/`.

## Ejemplos

```bash
spec init --root .
spec agent install claude --root . --yes
ws worktree /path/to/repo /path/to/worktree feature/payment
spec preflight payment --no-worktree
spec new payment --description "Validar pagos idempotentes"
progress new payment --title "Pago idempotente"
progress step payment add "Escribir tests"
spec verify --json
```

Ver [instalación](docs/installation.md), [agentes](docs/AGENTS_GUIDE.md),
[ejemplos](docs/examples.md), [referencia](docs/command-reference.md) y
[troubleshooting](docs/troubleshooting.md).

## Verificación

```bash
.venv/bin/python -m pytest -c pyproject.toml -v
.venv/bin/ruff check packages tests_acceptance scripts
.venv/bin/ruff format --check packages tests_acceptance scripts
```
