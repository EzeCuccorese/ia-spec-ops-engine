from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from spec.core.paths import PathBoundary


class OwnershipError(RuntimeError):
    """Base error for ownership-protected operations."""


class UnownedPathError(OwnershipError):
    """The requested path is not owned by this Spec installation."""


class FileChangedError(OwnershipError):
    """An owned file changed after Spec last wrote it."""


@dataclass(frozen=True)
class OwnershipRecord:
    path: str
    sha256: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DeleteResult:
    path: str
    deleted: bool
    would_delete: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OwnershipManifest:
    """Track exact generated files so cleanup cannot rely on names or prefixes."""

    schema_version = 1

    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.path = self.boundary.resolve(".spec/ownership.json")
        self._records = self._load()

    def _load(self) -> dict[str, OwnershipRecord]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema_version") != self.schema_version:
            raise OwnershipError("Unsupported ownership manifest schema")
        return {item["path"]: OwnershipRecord(**item) for item in data.get("files", [])}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "files": [
                asdict(record) for record in sorted(self._records.values(), key=lambda r: r.path)
            ],
        }
        fd, temporary_name = tempfile.mkstemp(prefix=".ownership-", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, candidate: str | Path) -> OwnershipRecord | None:
        return self._records.get(self.boundary.relative(candidate))

    def record(self, candidate: str | Path, sha256: str) -> OwnershipRecord:
        relative = self.boundary.relative(candidate)
        now = datetime.now(UTC).isoformat()
        existing = self._records.get(relative)
        record = OwnershipRecord(
            path=relative,
            sha256=sha256,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._records[relative] = record
        self._save()
        return record

    def assert_unchanged(self, candidate: str | Path) -> OwnershipRecord:
        relative = self.boundary.relative(candidate)
        record = self._records.get(relative)
        if record is None:
            raise UnownedPathError(f"Spec does not own: {relative}")
        target = self.boundary.resolve(relative)
        if not target.is_file() or target.is_symlink():
            raise FileChangedError(f"Owned path is no longer a regular file: {relative}")
        actual = sha256_file(target)
        if actual != record.sha256:
            raise FileChangedError(f"Owned file was modified after generation: {relative}")
        return record

    def delete_owned(self, candidate: str | Path, *, dry_run: bool = False) -> DeleteResult:
        record = self.assert_unchanged(candidate)
        if dry_run:
            return DeleteResult(path=record.path, deleted=False, would_delete=True)
        target = self.boundary.resolve(record.path)
        target.unlink()
        del self._records[record.path]
        self._save()
        return DeleteResult(path=record.path, deleted=True, would_delete=False)
