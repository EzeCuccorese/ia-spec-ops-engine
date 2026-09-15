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
uv pip install -e packages/ai-governance
uv pip install -e packages/spec
uv pip install -e packages/workspace
```

Para usar todo desde este checkout:

```bash
uv venv
uv pip install -e '.[dev]' -e packages/ai-governance -e packages/spec -e packages/workspace
ia-spec-ops-engine install --all --yes
```

Revisá una selección antes de confirmarla:

```bash
ia-spec-ops-engine install --components governance,spec
ia-spec-ops-engine install --components governance,spec --yes
```

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
python3 -m pytest -c pyproject.toml -v
ruff check packages tests_acceptance
```
