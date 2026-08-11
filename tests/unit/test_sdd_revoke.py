"""
Unit tests for devscripts.sdd.revoke module — SDD Revoke and Backup Restoration.
"""

import json
from pathlib import Path
import tempfile
import pytest

from devscripts.adapters.bridge import generate_adapters
from devscripts.sdd import memory, revoke


def test_backup_specify_dir(tmp_path):
    memory.init(target_dir=tmp_path)
    spec_dir = tmp_path / ".specify"
    (spec_dir / "specs" / "my-feature").mkdir(parents=True, exist_ok=True)
    (spec_dir / "specs" / "my-feature" / "spec.md").write_text("# Feature Spec", encoding="utf-8")

    backup_dir = revoke.backup_specify_dir(target_dir=tmp_path)
    assert backup_dir is not None
    assert backup_dir.exists()
    assert ".specify-backup-" in backup_dir.name
    assert (backup_dir / "specs" / "my-feature" / "spec.md").read_text(encoding="utf-8") == "# Feature Spec"


def test_revoke_sdd_configuration(tmp_path):
    memory.init(target_dir=tmp_path)
    generate_adapters(target_dir=tmp_path, gen_all=True)

    assert (tmp_path / ".specify").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".cursorrules").exists()
    assert (tmp_path / ".windsurfrules").exists()

    success, backup_path, removed = revoke.revoke_sdd_configuration(
        target_dir=tmp_path,
        create_backup=True,
        force=True,
    )

    assert success is True
    assert backup_path is not None
    assert backup_path.exists()
    assert len(removed) > 0

    assert not (tmp_path / ".specify").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".cursorrules").exists()
    assert not (tmp_path / ".windsurfrules").exists()


def test_revoke_without_backup(tmp_path):
    memory.init(target_dir=tmp_path)
    generate_adapters(target_dir=tmp_path, claude=True)

    success, backup_path, removed = revoke.revoke_sdd_configuration(
        target_dir=tmp_path,
        create_backup=False,
        force=True,
    )

    assert success is True
    assert backup_path is None
    assert not (tmp_path / ".specify").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_restore_backup_specs(tmp_path):
    memory.init(target_dir=tmp_path)
    spec_dir = tmp_path / ".specify"
    (spec_dir / "specs" / "feature-a").mkdir(parents=True, exist_ok=True)
    (spec_dir / "specs" / "feature-a" / "spec.md").write_text("# Feature A", encoding="utf-8")

    backup_dir = revoke.backup_specify_dir(target_dir=tmp_path)

    # Revoke configuration
    revoke.revoke_sdd_configuration(target_dir=tmp_path, create_backup=False, force=True)
    assert not (tmp_path / ".specify").exists()

    # Restore specs from backup
    restored = revoke.restore_backup_specs(backup_dir, target_dir=tmp_path)
    assert restored is True
    assert (tmp_path / ".specify" / "specs" / "feature-a" / "spec.md").exists()
    assert (tmp_path / ".specify" / "specs" / "feature-a" / "spec.md").read_text(encoding="utf-8") == "# Feature A"
