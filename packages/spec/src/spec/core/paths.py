from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PathSafetyError(ValueError):
    """Base error for unsafe filesystem targets."""


class UnsafeRootError(PathSafetyError):
    """The selected root is too broad for mutation operations."""


class PathOutsideRootError(PathSafetyError):
    """A requested path resolves outside the selected root."""


@dataclass(frozen=True)
class PathBoundary:
    """Resolve paths while enforcing a single explicit mutation root."""

    root: Path

    def __init__(self, root: str | Path) -> None:
        resolved = Path(root).expanduser().resolve()
        dangerous_roots = {Path("/").resolve(), Path.home().resolve()}
        if resolved in dangerous_roots:
            raise UnsafeRootError(f"Refusing broad mutation root: {resolved}")
        object.__setattr__(self, "root", resolved)

    def resolve(self, candidate: str | Path = ".") -> Path:
        raw = Path(candidate).expanduser()
        target = raw.resolve() if raw.is_absolute() else (self.root / raw).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise PathOutsideRootError(
                f"Path resolves outside allowed root: {candidate!s} -> {target}"
            ) from exc
        return target

    def relative(self, candidate: str | Path) -> str:
        return self.resolve(candidate).relative_to(self.root).as_posix()

