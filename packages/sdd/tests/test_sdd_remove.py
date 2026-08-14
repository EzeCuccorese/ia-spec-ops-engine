"""
Unit tests for sdd_engine.revoke / sdd remove and worktree sync functionality.
"""

import tempfile
from pathlib import Path
import pytest

from sdd_engine.revoke import revoke_sdd_configuration, backup_specify_dir
from sdd_engine.sync import get_active_repo_worktrees


def test_revoke_sdd_configuration_creates_backup_and_cleans():
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)

        # Create dummy SDD & adapter files
        spec_dir = td / ".specify"
        spec_dir.mkdir()
        (spec_dir / "memory.md").write_text("# Test Memory")

        agents_dir = td / ".agents"
        agents_dir.mkdir()
        (agents_dir / "AGENTS.md").write_text("# Test Agents")
        (td / "AGENTS.md").write_text("# Test Agents Root")

        # Execute revoke with force=True
        success, backup_path, removed = revoke_sdd_configuration(target_dir=td, force=True)

        assert success is True
        assert backup_path is not None
        assert backup_path.exists()
        assert (backup_path / "memory.md").exists()

        # Check clean up
        assert not (td / ".specify").exists()
        assert not (td / ".agents").exists()
        assert not (td / "AGENTS.md").exists()


def test_get_active_repo_worktrees_non_git():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Non-git directory returns empty list
        wts = get_active_repo_worktrees(tmp_dir)
        assert wts == []
