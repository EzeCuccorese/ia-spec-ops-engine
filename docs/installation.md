# Instalación

Python 3.11+ es necesario para `ai-governance` y `spec`; `workspace` admite
Python 3.10+. Git es requerido para worktrees. `uv` es recomendado.

```bash
uv pip install -e packages/ai-governance
uv pip install -e packages/spec
uv pip install -e packages/workspace
```

Cada módulo funciona por separado. Para el checkout completo:

```bash
uv pip install -e '.[dev]' -e packages/ai-governance -e packages/spec -e packages/workspace
ia-spec-ops-engine install --all --yes
```

Comprobá con `ia-spec-ops-engine --help`, `spec --help`, `ws --help` y
`governance --help`.
