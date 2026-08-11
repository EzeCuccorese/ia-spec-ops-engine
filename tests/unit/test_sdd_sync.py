"""
Unit tests for devscripts.sdd.sync module — SDD Global & Local Synchronization.
"""

from pathlib import Path
import tempfile
import pytest

from devscripts.sdd import sync


def test_sync_sdd_uninitialized(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "1")

    success, synced_files = sync.sync_sdd(target_dir=tmp_path, quiet=True)
    assert success is True
    assert (tmp_path / ".specify").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert len(synced_files) > 0


def test_sync_sdd_already_initialized(tmp_path):
    (tmp_path / ".specify").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".specify" / "agents.json").write_text('{"selected_agents": ["claude"]}', encoding="utf-8")

    success, synced_files = sync.sync_sdd(target_dir=tmp_path, quiet=True)
    assert success is True
    assert "CLAUDE.md" in synced_files
    assert (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()
