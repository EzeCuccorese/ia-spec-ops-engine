"""Company packs (``packages/corporate-rules/<pack>/``): always-on rules and scripts.

Packs live next to the packages in the source checkout (gitignored, never bundled in
the wheel) or wherever ``AI_GOVERNANCE_CORPORATE_DIR`` points. Installed at user scope
only when the user names the pack (``--corporate <pack>``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CORPORATE_DIR = "corporate-rules"


def corporate_root() -> Path:
    explicit = os.environ.get("AI_GOVERNANCE_CORPORATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    # src/ai_governance/corporate.py -> packages/corporate-rules (editable/source install).
    return Path(__file__).resolve().parents[3] / CORPORATE_DIR


def bin_dir() -> Path:
    explicit = os.environ.get("AI_GOVERNANCE_BIN_DIR")
    return Path(explicit).expanduser() if explicit else Path.home() / ".local" / "bin"


@dataclass(frozen=True)
class CorporateRule:
    pack: str
    name: str
    content: str


@dataclass(frozen=True)
class CorporatePack:
    name: str
    root: Path

    def rules(self) -> list[CorporateRule]:
        return [
            CorporateRule(self.name, path.stem, path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "rules").glob("*.md"))
        ]

    def scripts(self) -> list[Path]:
        folder = self.root / "scripts"
        return sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []


def available(root: Path | None = None) -> list[str]:
    base = root or corporate_root()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))


def load(name: str, root: Path | None = None) -> CorporatePack:
    names = available(root)
    if name not in names:
        raise ValueError(
            f"Unknown corporate pack: {name}. Choose from: {', '.join(names) or '(none)'}"
        )
    return CorporatePack(name, (root or corporate_root()) / name)
