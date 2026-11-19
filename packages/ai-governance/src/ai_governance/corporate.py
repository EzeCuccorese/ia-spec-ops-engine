"""Company packs with always-on rules and scripts.

Packs live outside the source checkout under the user config directory, or wherever
``AI_GOVERNANCE_CORPORATE_DIR`` points. Every pack present is installed at user scope.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import check_frontmatter
from .paths import config_dir
from .settings import effective

CORPORATE_DIR = "corporate-rules"


def corporate_root() -> Path:
    explicit = os.environ.get("AI_GOVERNANCE_CORPORATE_DIR")
    root = Path(explicit).expanduser() if explicit else config_dir() / CORPORATE_DIR
    return _validate_private_root(root)


def _validate_private_root(root: Path) -> Path:
    declared = Path(os.path.abspath(root))
    resolved = root.resolve()
    candidates = {declared, *declared.parents, resolved, *resolved.parents}
    if any((parent / ".git").exists() for parent in candidates):
        raise ValueError("Corporate packs must be stored outside Git worktrees.")
    return resolved


def _pack_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("Corporate pack directories must not alias another location.")
    return _validate_private_root(root)


def rule_paths(root: Path, pack_name: str) -> list[Path]:
    """Returns Markdown rules for one pack after validating every resolved source path."""
    base = _validate_private_root(root)
    pack_root = _pack_root(base / pack_name)
    folder = pack_root / "rules"
    if not folder.is_dir():
        return []
    if folder.is_symlink():
        raise ValueError("Corporate rule directories must not alias another location.")
    paths: list[Path] = []
    for path in folder.glob("*.md"):
        if not path.is_file() or path.name.lower() == "readme.md":
            continue
        if path.is_symlink():
            raise ValueError("Corporate rule files must not alias another location.")
        paths.append(_validate_private_root(path))
    return sorted(paths)


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
        result: list[CorporateRule] = []
        for private_path in rule_paths(self.root.parent, self.name):
            content = private_path.read_text(encoding="utf-8")
            check = check_frontmatter(content)
            if not check.valid:
                warnings.warn(
                    f"Corporate rule '{private_path.name}' in pack '{self.name}' ({private_path}) is missing YAML front matter with 'trigger: always_on' or 'trigger: glob'",
                    UserWarning,
                    stacklevel=2,
                )
            result.append(CorporateRule(self.name, private_path.stem, content, private_path))
        return result

    def skills(self) -> list[Path]:
        """Skill directories of the pack: every ``skills/<name>/`` holding a ``SKILL.md``."""
        folder = _pack_root(self.root) / "skills"
        if not folder.is_dir():
            return []
        if folder.is_symlink():
            raise ValueError("Corporate skill directories must not alias another location.")
        return sorted(
            p
            for p in folder.iterdir()
            if p.is_dir()
            and not p.name.startswith(".")
            and not p.is_symlink()
            and _validate_private_root(p).joinpath("SKILL.md").is_file()
        )

    def scripts(self) -> list[Path]:
        folder = _pack_root(self.root) / "scripts"
        if folder.is_symlink():
            raise ValueError("Corporate script directories must not alias another location.")
        return (
            sorted(
                _validate_private_root(p)
                for p in folder.iterdir()
                if p.is_file() and not p.is_symlink()
            )
            if folder.is_dir()
            else []
        )


def available(root: Path | None = None) -> list[str]:
    base = _validate_private_root(root) if root is not None else corporate_root()
    if not base.is_dir():
        return []
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
    )


def packs(root: Path | None = None, only: Sequence[str] | None = None) -> list[CorporatePack]:
    """The packs present on disk, or exactly the ones chosen.

    ``only`` (``--corporate``) wins; otherwise ``corporate.packs`` / ``AI_GOVERNANCE_CORPORATE``
    when set. An explicit empty choice selects no pack; nothing chosen at all installs every
    pack present. A name that is not a folder of the corporate root raises ``ValueError``
    listing the available packs, so a typo never silently installs nothing.
    """
    base = root or corporate_root()
    present = available(base)
    wanted = list(only) if only is not None else selected_names()
    unknown = [name for name in wanted or [] if name not in present]
    if unknown:
        raise ValueError(
            f"Unknown corporate pack(s): {', '.join(unknown)}. Available: {', '.join(present) or '(none)'}"
        )
    return [
        CorporatePack(name, _pack_root(base / name))
        for name in (present if wanted is None else wanted)
    ]


def selected_names(flag: str | None = None) -> list[str] | None:
    """``--corporate`` > ``AI_GOVERNANCE_CORPORATE`` > ``[corporate] packs``.

    None means nothing was chosen (every pack); an empty list means "no pack" because the
    flag, variable or file said so explicitly.
    """
    flags: dict[str, object] | None = {"corporate.packs": flag} if flag is not None else None
    chosen = effective(flags=flags)["corporate.packs"]
    if chosen.origin == "default":
        return None
    return [str(name) for name in chosen.value]  # type: ignore[attr-defined]
