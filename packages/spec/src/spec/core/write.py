from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from spec.core.ownership import FileChangedError, OwnershipManifest, sha256_file
from spec.core.paths import PathBoundary


class SafeWriteError(RuntimeError):
    """Base error for protected writes."""


class TargetExistsError(SafeWriteError):
    """A target exists but is not safe for Spec to overwrite."""


@dataclass(frozen=True)
class WriteResult:
    path: str
    sha256: str
    created: bool
    updated: bool


class SafeWriter:
    """Perform atomic writes and couple every generated file to explicit ownership."""

    def __init__(self, root: str | Path, manifest: OwnershipManifest | None = None) -> None:
        self.boundary = PathBoundary(root)
        self.manifest = manifest or OwnershipManifest(root)

    def write(
        self,
        candidate: str | Path,
        content: str,
        *,
        mode: int = 0o600,
    ) -> WriteResult:
        target = self.boundary.resolve(candidate)
        relative = self.boundary.relative(target)
        existing_record = self.manifest.get(relative)
        created = not target.exists()

        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise TargetExistsError(f"Refusing non-regular target: {relative}")
            if existing_record is None:
                raise TargetExistsError(f"Refusing to overwrite unowned file: {relative}")
            try:
                self.manifest.assert_unchanged(relative)
            except FileChangedError as exc:
                raise TargetExistsError(str(exc)) from exc

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

        digest = sha256_file(target)
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest != expected:
            raise SafeWriteError(f"Post-write digest mismatch for {relative}")
        self.manifest.record(relative, digest)
        return WriteResult(path=relative, sha256=digest, created=created, updated=not created)

