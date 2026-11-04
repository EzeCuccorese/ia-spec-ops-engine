"""Personal preference packs (``~/.config/ai-governance/personal/``): always-on rules.

Personal rules live outside the repository in ``$AI_GOVERNANCE_PERSONAL_DIR`` or
``$AI_GOVERNANCE_CONFIG_DIR/personal`` (default ``~/.config/ai-governance/personal``).
Every rule present in ``<root>/rules/*.md`` is installed as a symlink for each selected agent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .paths import config_dir

PERSONAL_DIR = "personal"


def personal_root() -> Path:
    explicit = os.environ.get("AI_GOVERNANCE_PERSONAL_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return config_dir() / PERSONAL_DIR


@dataclass(frozen=True)
class PersonalRule:
    name: str
    content: str
    path: Path


@dataclass(frozen=True)
class PersonalPack:
    root: Path

    def rules(self) -> list[PersonalRule]:
        folder = self.root / "rules"
        if not folder.is_dir():
            return []
        return [
            PersonalRule(path.stem, path.read_text(encoding="utf-8"), path.resolve())
            for path in sorted(folder.glob("*.md"))
        ]


def pack(root: Path | None = None) -> PersonalPack:
    return PersonalPack(root or personal_root())


def rules(root: Path | None = None) -> list[PersonalRule]:
    return pack(root).rules()
