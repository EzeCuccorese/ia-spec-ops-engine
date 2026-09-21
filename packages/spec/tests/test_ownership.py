from pathlib import Path

import pytest
import spec.core.write as write_module
from spec.core.ownership import (
    FileChangedError,
    OwnershipError,
    OwnershipManifest,
    UnownedPathError,
)
from spec.core.write import SafeWriteError, SafeWriter, TargetExistsError


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


def test_safe_writer_refuses_non_regular_target(tmp_path: Path) -> None:
    directory_target = tmp_path / "a-directory"
    directory_target.mkdir()
    writer = SafeWriter(tmp_path, OwnershipManifest(tmp_path))

    with pytest.raises(TargetExistsError, match="non-regular"):
        writer.write("a-directory", "spec content\n")


def test_safe_writer_refuses_owned_file_modified_by_user(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    writer = SafeWriter(tmp_path, manifest)
    writer.write(".spec/generated.txt", "original\n")
    target = tmp_path / ".spec/generated.txt"
    target.write_text("user edit\n")

    with pytest.raises(TargetExistsError):
        writer.write(".spec/generated.txt", "new content\n")


def test_safe_writer_raises_on_post_write_digest_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SafeWriter(tmp_path, OwnershipManifest(tmp_path))
    monkeypatch.setattr(write_module, "sha256_file", lambda _target: "deadbeef")

    with pytest.raises(SafeWriteError, match="digest mismatch"):
        writer.write(".spec/generated.txt", "content\n")


def test_delete_owned_file_supports_dry_run(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    SafeWriter(tmp_path, manifest).write(".spec/generated.txt", "original\n")

    result = manifest.delete_owned(".spec/generated.txt", dry_run=True)

    assert result.deleted is False
    assert result.would_delete is True
    assert (tmp_path / ".spec/generated.txt").exists()


def test_delete_owned_file_removes_target_and_record(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    SafeWriter(tmp_path, manifest).write(".spec/generated.txt", "original\n")

    result = manifest.delete_owned(".spec/generated.txt")

    assert result.deleted is True
    assert result.would_delete is False
    assert not (tmp_path / ".spec/generated.txt").exists()
    assert manifest.get(".spec/generated.txt") is None


def test_manifest_load_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".spec/ownership.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        '{"schema_version": 2, "files": []}',
        encoding="utf-8",
    )

    with pytest.raises(OwnershipError, match="Unsupported ownership manifest schema"):
        OwnershipManifest(tmp_path)


def test_manifest_reloads_existing_records_from_disk(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    SafeWriter(tmp_path, manifest).write(".spec/generated.txt", "original\n")

    reloaded = OwnershipManifest(tmp_path)
    record = reloaded.get(".spec/generated.txt")

    assert record is not None
    assert record.sha256 == manifest.get(".spec/generated.txt").sha256


def test_assert_unchanged_rejects_owned_path_no_longer_a_regular_file(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tmp_path)
    SafeWriter(tmp_path, manifest).write(".spec/generated.txt", "original\n")
    target = tmp_path / ".spec/generated.txt"
    target.unlink()
    target.mkdir()

    with pytest.raises(FileChangedError, match="no longer a regular file"):
        manifest.assert_unchanged(".spec/generated.txt")
