# Instalación

Python 3.11+ es necesario para `ai-governance` y `spec`; `workspace` admite
Python 3.10+. Git es requerido para worktrees. `uv` es recomendado.

```bash
uv venv
source .venv/bin/activate
uv pip install -e packages/ai-governance
uv pip install -e packages/spec
uv pip install -e packages/workspace
```

Cada módulo funciona por separado. Para el checkout completo:

```bash
./install.sh
source .venv/bin/activate
```

`install.sh` crea o reutiliza `.venv` e instala los tres paquetes con sus dependencias
de desarrollo. Usa `uv` cuando está disponible y `venv`/`pip` en caso contrario.
No instala una cuarta distribución raíz. Sin activar el entorno, usá `./bin/specops`,
`./bin/spec` y `./bin/ws`, que seleccionan el Python del checkout.

Para comprobar los wheels desde entornos vacíos externos al checkout:

```bash
uv build packages/ai-governance --wheel --out-dir dist
uv build packages/spec --wheel --out-dir dist
uv build packages/workspace --wheel --out-dir dist
.venv/bin/python scripts/verify_wheels.py dist
```

Comprobá con `specops --help`, `spec --help`, `ws --help` y `governance --help`.
