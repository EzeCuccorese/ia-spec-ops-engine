"""
Unit tests for workspace_engine.cli.clean_workspace.

All filesystem effects happen under tmp_path.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli import clean_workspace as cw


def test_clean_workspace_no_ai_toolkit_or_repositories(tmp_path: Path) -> None:
    rc = cw.clean_workspace(start_dir=tmp_path)
    assert rc == 0


def test_clean_workspace_removes_ai_toolkit_entries_except_manifest(tmp_path: Path) -> None:
    ai_dir = tmp_path / ".ai-toolkit"
    ai_dir.mkdir()
    (ai_dir / "workspace.json").write_text("{}", encoding="utf-8")
    stale_dir = ai_dir / "run-pids"
    stale_dir.mkdir()
    (stale_dir / "repo.pid").write_text("123")
    stale_file = ai_dir / "cache.tmp"
    stale_file.write_text("x")

    rc = cw.clean_workspace(start_dir=tmp_path)

    assert rc == 0
    assert (ai_dir / "workspace.json").exists()
    assert not stale_dir.exists()
    assert not stale_file.exists()


def test_clean_workspace_cleans_repo_cache_directories(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repo_a = repos_dir / "repo-a"
    (repo_a / "node_modules").mkdir(parents=True)
    (repo_a / "node_modules" / "pkg.js").write_text("x")
    (repo_a / "build").mkdir()
    not_a_repo = repos_dir / "not-a-dir.txt"
    repos_dir.mkdir(exist_ok=True)
    not_a_repo.write_text("x")

    rc = cw.clean_workspace(start_dir=tmp_path)

    assert rc == 0
    assert not (repo_a / "node_modules").exists()
    assert not (repo_a / "build").exists()
    assert not_a_repo.exists()  # untouched, not a repo directory


def test_clean_workspace_skips_non_dir_repo_entries(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "readme.txt").write_text("x")

    rc = cw.clean_workspace(start_dir=tmp_path)
    assert rc == 0


def test_clean_workspace_unlinks_symlinked_cache_dir(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repo_a = repos_dir / "repo-a"
    repo_a.mkdir(parents=True)
    real_target = tmp_path / "real-node-modules"
    real_target.mkdir()
    symlink = repo_a / "node_modules"
    symlink.symlink_to(real_target, target_is_directory=True)

    rc = cw.clean_workspace(start_dir=tmp_path)

    assert rc == 0
    assert not symlink.exists() and not symlink.is_symlink()
    assert real_target.exists()  # the symlink target itself is untouched


def test_clean_workspace_unlinks_symlinked_ai_toolkit_entry(tmp_path: Path) -> None:
    ai_dir = tmp_path / ".ai-toolkit"
    ai_dir.mkdir()
    real_target = tmp_path / "real-dir"
    real_target.mkdir()
    symlink = ai_dir / "linked"
    symlink.symlink_to(real_target, target_is_directory=True)

    rc = cw.clean_workspace(start_dir=tmp_path)

    assert rc == 0
    assert not symlink.exists() and not symlink.is_symlink()
    assert real_target.exists()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_forwards_exit_code() -> None:
    with (
        patch("sys.argv", ["clean-workspace"]),
        patch.object(cw, "clean_workspace", return_value=0) as mock_clean,
        pytest.raises(SystemExit) as exc,
    ):
        cw.main()
    assert exc.value.code == 0
    mock_clean.assert_called_once_with()


def test_clean_workspace_reports_in_english(tmp_path: Path, capsys) -> None:
    (tmp_path / "repositories" / "svc" / "dist").mkdir(parents=True)
    assert cw.clean_workspace(tmp_path) == 0
    out = capsys.readouterr().out
    assert f"removing: {tmp_path / 'repositories' / 'svc' / 'dist'}" in out
    assert "[clean-workspace] Cleanup completed." in out
