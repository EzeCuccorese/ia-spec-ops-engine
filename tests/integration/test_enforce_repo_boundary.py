"""
Integration tests for repository boundary enforcement and worktree creation logic.
"""

from pathlib import Path
from devscripts.cli.create_worktree import create_worktree

def test_create_worktree_existing_dir_fails(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    existing_worktree = tmp_path.parent / "niat-feature-test"
    existing_worktree.mkdir()

    res = create_worktree("feature/test", start_dir=tmp_path)
    assert res == 1
