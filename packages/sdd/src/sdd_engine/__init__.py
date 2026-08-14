"""
sdd_engine — Motor de Inteligencia Artificial y Gobernanza para Spec-Driven Development (SDD).

Estructurado en capas de Clean Architecture con carga diferida (Lazy Loading):
- sdd_engine.core: Dominio, invariantes, parser, excepciones y utilidades base.
- sdd_engine.lifecycle: Gestión del ciclo de vida de las 8 fases.
- sdd_engine.harness: Motor de gobernanza, arnés de ejecución (tasks.md), calidad y hooks.
- sdd_engine.adapters: Compilador Multi-IA (bridge), gestor de skills globales, reset y sync.
- sdd_engine.cli: Puntos de entrada CLI y dashboard TUI.
"""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "0.2.0"

_SUBMODULE_MAP = {
    # Core
    "exceptions": "sdd_engine.core.exceptions",
    "invariants": "sdd_engine.core.invariants",
    "memory": "sdd_engine.core.memory",
    "parser": "sdd_engine.core.parser",
    "utils": "sdd_engine.core.utils",
    # Lifecycle
    "constitution": "sdd_engine.lifecycle.constitution",
    "feature": "sdd_engine.lifecycle.feature",
    "finish": "sdd_engine.lifecycle.finish",
    # Harness
    "analyzer": "sdd_engine.harness.analyzer",
    "harness": "sdd_engine.harness.harness",
    "harness_mod": "sdd_engine.harness.harness",
    "hooks": "sdd_engine.harness.hooks",
    "quality_gate": "sdd_engine.harness.quality_gate",
    "runner": "sdd_engine.harness.runner",
    "verify": "sdd_engine.harness.verify",
    # Adapters
    "bridge": "sdd_engine.adapters.bridge",
    "global_skills": "sdd_engine.adapters.global_skills",
    "reset": "sdd_engine.adapters.reset",
    "revoke": "sdd_engine.adapters.revoke",
    "sync": "sdd_engine.adapters.sync",
    # Packages
    "core": "sdd_engine.core",
    "lifecycle": "sdd_engine.lifecycle",
    "harness_pkg": "sdd_engine.harness",
    "adapters": "sdd_engine.adapters",
    "cli": "sdd_engine.cli",
    "sdd_tui": "sdd_engine.cli.sdd_tui",
}


def __getattr__(name: str) -> Any:
    """Implementa lazy loading transparente para módulos sin costo de importación inicial."""
    if name == "main":
        from sdd_engine.cli.cli import main
        return main
    if name in _SUBMODULE_MAP:
        return importlib.import_module(_SUBMODULE_MAP[name])
    raise AttributeError(f"module 'sdd_engine' has no attribute '{name}'")


def main() -> None:
    from sdd_engine.cli.cli import main as _cli_main
    _cli_main()


__all__ = [
    "main",
    "core",
    "lifecycle",
    "harness",
    "adapters",
    "cli",
]
