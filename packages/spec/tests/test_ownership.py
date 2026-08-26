from pathlib import Path

import pytest

from spec.core.ownership import FileChangedError, OwnershipManifest, UnownedPathError
from spec.core.write import SafeWriter, TargetExistsError


def test_safe_writer_creates_and_tracks_owned_file(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    writer = SafeWriter(tmp_path, manifest)

    result = writer.write(".spec/generated.txt", "generated\n")

    assert result.created is True
    assert (tmp_path / ".spec/generated.txt").read_text() == "generated\n"
    record = manifest.get(".spec/generated.txt")
    assert record is not None
    assert record.sha256 == result.sha256


def test_safe_writer_does_not_overwrite_unowned_file(tmp_path: Path) -> None:
    existing = tmp_path / "AGENTS.md"
    existing.write_text("user content\n")
    writer = SafeWriter(tmp_path, OwnershipManifest(tmp_path))

    with pytest.raises(TargetExistsError):
        writer.write("AGENTS.md", "spec content\n")

    assert existing.read_text() == "user content\n"


def test_delete_rejects_unowned_file(tmp_path: Path) -> None:
    existing = tmp_path / "notes.md"
    existing.write_text("keep me\n")
    manifest = OwnershipManifest(tmp_path)

    with pytest.raises(UnownedPathError):
        manifest.delete_owned("notes.md")

    assert existing.exists()


def test_delete_rejects_owned_file_modified_by_user(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    writer = SafeWriter(tmp_path, manifest)
    writer.write(".spec/generated.txt", "original\n")
    target = tmp_path / ".spec/generated.txt"
    target.write_text("user edit\n")

    with pytest.raises(FileChangedError):
        manifest.delete_owned(".spec/generated.txt")

    assert target.read_text() == "user edit\n"


def test_delete_owned_file_supports_dry_run(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    SafeWriter(tmp_path, manifest).write(".spec/generated.txt", "original\n")

    result = manifest.delete_owned(".spec/generated.txt", dry_run=True)

    assert result.deleted is False
    assert result.would_delete is True
    assert (tmp_path / ".spec/generated.txt").exists()

