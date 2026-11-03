"""Company packs (``packages/corporate-rules/<pack>/``): always-on rules and scripts.

Packs live next to the packages in the source checkout (gitignored, never bundled in
the wheel) or wherever ``AI_GOVERNANCE_CORPORATE_DIR`` points. Every pack present is
installed at user scope; a company is just a folder, so switching companies means
swapping folders.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .settings import get as setting

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
    path: Path


@dataclass(frozen=True)
class CorporatePack:
    name: str
    root: Path

    def rules(self) -> list[CorporateRule]:
        return [
            CorporateRule(self.name, path.stem, path.read_text(encoding="utf-8"), path.resolve())
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


def packs(root: Path | None = None, only: Sequence[str] | None = None) -> list[CorporatePack]:
    """The packs present on disk, or just ``only`` (default: ``corporate.packs``, empty = all).

    A name that is not a folder of the corporate root raises ``ValueError`` listing the
    available packs, so a typo never silently installs nothing.
    """
    base = root or corporate_root()
    present = available(base)
    wanted = list(only) if only is not None else list(selected_names())
    unknown = [name for name in wanted if name not in present]
    if unknown:
        raise ValueError(
            f"Unknown corporate pack(s): {', '.join(unknown)}. Available: {', '.join(present) or '(none)'}"
        )
    return [CorporatePack(name, base / name) for name in (wanted or present)]


def selected_names(flag: str | None = None) -> list[str]:
    """``--corporate`` > ``AI_GOVERNANCE_CORPORATE`` > ``[corporate] packs`` > every pack."""
    chosen = setting("corporate.packs", flags={"corporate.packs": flag} if flag else None)
    return [str(name) for name in chosen]  # type: ignore[attr-defined]
