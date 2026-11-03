"""Every spec setting: default, environment variable and where it is read.

Layers (lowest to highest): default < ``~/.config/spec/config.toml`` <
``<repo>/.spec/config.toml`` < environment variable < CLI flag.
"""

from __future__ import annotations

from pathlib import Path

from ._config_core import Layers, Setting, Value, load_layers, resolve

APP_NAME = "spec"

SETTINGS: tuple[Setting, ...] = (
    Setting(
        "verify.timeout_seconds",
        300,
        "SPEC_VERIFY_TIMEOUT_SECONDS",
        "Default timeout of a verification check that sets no `timeout_seconds` of its own",
    ),
)


def layers(root: Path | None = None) -> Layers:
    return load_layers(APP_NAME, root)


def effective(root: Path | None = None) -> dict[str, Value]:
    return resolve(SETTINGS, layers(root))


def get(key: str, root: Path | None = None) -> object:
    return effective(root)[key].value
