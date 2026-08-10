"""
Integration tests for clean_workspace functionality using temporary file structures.
"""

from pathlib import Path
from devscripts.cli.clean_workspace import clean_workspace

def test_clean_workspace_removes_cache(tmp_path: Path):
    # Setup mock workspace structure
    (tmp_path / ".git").mkdir()
    ai_dir = tmp_path / ".ai-toolkit"
    ai_dir.mkdir()
    (ai_dir / "workspace.json").write_text('{"repos": []}')
    (ai_dir / "cache.log").write_text("dummy log")

    repo_dir = tmp_path / "repositories" / "my-service"
    repo_dir.mkdir(parents=True)
    (repo_dir / "node_modules").mkdir()
    (repo_dir / ".gradle").mkdir()

    res = clean_workspace(start_dir=tmp_path)
    assert res == 0
    assert (ai_dir / "workspace.json").exists()
    assert not (ai_dir / "cache.log").exists()
    assert not (repo_dir / "node_modules").exists()
    assert not (repo_dir / ".gradle").exists()
