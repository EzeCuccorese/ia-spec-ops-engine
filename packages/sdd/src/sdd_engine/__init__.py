"""
sdd_engine — Motor de Inteligencia Artificial y Gobernanza para Spec-Driven Development (SDD).

Estructurado en capas de Clean Architecture:
- sdd_engine.core: Dominio, invariantes, parser, excepciones y utilidades base.
- sdd_engine.lifecycle: Gestión del ciclo de vida de las 8 fases (.specify/feature.json, finish, constitution).
- sdd_engine.harness: Motor de gobernanza, arnés de ejecución (tasks.md), calidad y hooks.
- sdd_engine.adapters: Compilador Multi-IA (bridge), gestor de skills globales, reset y sync.
- sdd_engine.cli: Puntos de entrada CLI y dashboard TUI.
"""

from __future__ import annotations

import sys

# Subpaquetes
from sdd_engine import adapters, cli, core, harness, lifecycle

# Re-export de módulos para compatibilidad total
from sdd_engine.core import exceptions, invariants, memory, parser, utils
from sdd_engine.lifecycle import constitution, feature, finish
from sdd_engine.harness import analyzer, harness as harness_mod, hooks, quality_gate, runner, verify
from sdd_engine.adapters import bridge, global_skills, reset, revoke, sync
from sdd_engine.cli import cli as cli_mod, sdd_tui

# Alias de compatibilidad en sys.modules para imports directos antiguos
sys.modules["sdd_engine.exceptions"] = exceptions
sys.modules["sdd_engine.invariants"] = invariants
sys.modules["sdd_engine.memory"] = memory
sys.modules["sdd_engine.parser"] = parser
sys.modules["sdd_engine.utils"] = utils
sys.modules["sdd_engine.constitution"] = constitution
sys.modules["sdd_engine.feature"] = feature
sys.modules["sdd_engine.finish"] = finish
sys.modules["sdd_engine.analyzer"] = analyzer
sys.modules["sdd_engine.harness"] = harness_mod
sys.modules["sdd_engine.hooks"] = hooks
sys.modules["sdd_engine.quality_gate"] = quality_gate
sys.modules["sdd_engine.runner"] = runner
sys.modules["sdd_engine.verify"] = verify
sys.modules["sdd_engine.bridge"] = bridge
sys.modules["sdd_engine.global_skills"] = global_skills
sys.modules["sdd_engine.reset"] = reset
sys.modules["sdd_engine.revoke"] = revoke
sys.modules["sdd_engine.sync"] = sync
sys.modules["sdd_engine.sdd_tui"] = sdd_tui

main = cli_mod.main

__all__ = [
    "core",
    "lifecycle",
    "harness",
    "adapters",
    "cli",
    "main",
    "analyzer",
    "bridge",
    "constitution",
    "exceptions",
    "feature",
    "finish",
    "global_skills",
    "harness_mod",
    "hooks",
    "invariants",
    "memory",
    "parser",
    "quality_gate",
    "reset",
    "revoke",
    "runner",
    "sync",
    "utils",
    "verify",
]
