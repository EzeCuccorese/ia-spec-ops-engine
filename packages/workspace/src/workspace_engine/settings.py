"""Every ws setting in one place: default, environment variable and where it is read.

Layers (lowest to highest): default < ``~/.config/workspace/config.toml`` <
``<repo>/.workspace/config.toml`` < environment variable < CLI flag.

``config.json`` next to those files is the ``run-local`` project file (``ws config init``),
not a settings layer: ``project.*`` keys in ``ws config show`` come from it.
"""

from __future__ import annotations

from pathlib import Path

from ._config_core import Layers, Setting, Value, load_layers, resolve

APP_NAME = "workspace"

SETTINGS: tuple[Setting, ...] = ()


def repo_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor holding ``.git`` or ``.workspace``; None outside a repository."""
    here = (start or Path.cwd()).resolve()
    for folder in [here, *here.parents]:
        if (folder / ".git").exists() or (folder / ".workspace").is_dir():
            return folder
    return None


def layers(root: Path | None = None) -> Layers:
    return load_layers(APP_NAME, root if root is not None else repo_root(), legacy_json=False)


def effective(root: Path | None = None, flags: dict[str, object] | None = None) -> dict[str, Value]:
    return resolve(SETTINGS, layers(root), flags=flags)


def get(key: str, root: Path | None = None) -> object:
    """Effective value of one setting (default < user < repo < env)."""
    return effective(root)[key].value
