"""
Unit tests for workspace_engine.cli.edit_workspace.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli import edit_workspace


def _make_workspace(tmp_path: Path, repos: list[str]) -> Path:
    workspace_dir = tmp_path / "ws"
    (workspace_dir / ".ai-toolkit").mkdir(parents=True)
    (workspace_dir / "repositories").mkdir()
    manifest = {
        "workspace": "ws",
        "repositories": [{"name": r} for r in repos],
    }
    (workspace_dir / ".ai-toolkit" / "workspace.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return workspace_dir


def test_remove_repositories_missing_manifest_exits(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    with pytest.raises(SystemExit) as exc:
        edit_workspace.remove_repositories_from_workspace(workspace_dir)
    assert exc.value.code == 1


def test_remove_repositories_no_repos_in_workspace(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, [])
    # Should just print an info message and return without raising.
    edit_workspace.remove_repositories_from_workspace(workspace_dir)


def test_remove_repositories_cancelled_with_empty_input(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a"])
    with patch("builtins.input", return_value=""):
        edit_workspace.remove_repositories_from_workspace(workspace_dir)


def test_remove_repositories_cancelled_with_q(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a"])
    with patch("builtins.input", return_value="q"):
        edit_workspace.remove_repositories_from_workspace(workspace_dir)


def test_remove_repositories_no_valid_selection(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a"])
    with patch("builtins.input", return_value="not-a-number"):
        edit_workspace.remove_repositories_from_workspace(workspace_dir)


def test_remove_repositories_removes_selected_repo(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a", "repo-b"])
    target_wt = workspace_dir / "repositories" / "repo-a"
    target_wt.mkdir()

    with (
        patch("builtins.input", return_value="1"),
        patch.object(edit_workspace, "run_git") as mock_run_git,
        patch.object(edit_workspace, "update_workspace_agents") as mock_update,
    ):
        mock_run_git.return_value.returncode = 1
        mock_run_git.return_value.stdout = ""
        edit_workspace.remove_repositories_from_workspace(workspace_dir)

    assert not target_wt.exists()
    mock_update.assert_called_once()
    manifest = json.loads(
        (workspace_dir / ".ai-toolkit" / "workspace.json").read_text(encoding="utf-8")
    )
    assert [r["name"] for r in manifest["repositories"]] == ["repo-b"]


def test_remove_repositories_ignores_out_of_range_index(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a", "repo-b"])
    target_wt = workspace_dir / "repositories" / "repo-a"
    target_wt.mkdir()

    with (
        patch("builtins.input", return_value="1,99"),
        patch.object(edit_workspace, "run_git") as mock_run_git,
        patch.object(edit_workspace, "update_workspace_agents") as mock_update,
    ):
        mock_run_git.return_value.returncode = 1
        mock_run_git.return_value.stdout = ""
        edit_workspace.remove_repositories_from_workspace(workspace_dir)

    assert not target_wt.exists()
    mock_update.assert_called_once_with(workspace_dir, ["repo-b"])


def test_remove_repositories_skips_missing_worktree_dir(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a"])
    # repo-a is listed in the manifest but has no directory on disk.

    with (
        patch("builtins.input", return_value="1"),
        patch.object(edit_workspace, "update_workspace_agents") as mock_update,
    ):
        edit_workspace.remove_repositories_from_workspace(workspace_dir)

    mock_update.assert_called_once_with(workspace_dir, [])


def test_remove_repositories_uses_git_common_dir_absolute(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a"])
    target_wt = workspace_dir / "repositories" / "repo-a"
    target_wt.mkdir()
    common_dir = tmp_path / "common-git-dir"
    common_dir.mkdir()

    def fake_run_git(path: Path, *args: str):
        result = type("R", (), {})()
        if args[:2] == ("rev-parse", "--git-common-dir"):
            result.returncode = 0
            result.stdout = str(common_dir) + "\n"
        else:
            result.returncode = 0
            result.stdout = ""
        return result

    with (
        patch("builtins.input", return_value="1"),
        patch.object(edit_workspace, "run_git", side_effect=fake_run_git),
        patch.object(edit_workspace, "update_workspace_agents"),
    ):
        edit_workspace.remove_repositories_from_workspace(workspace_dir)

    assert not target_wt.exists()


def test_remove_repositories_uses_git_common_dir_relative(tmp_path: Path) -> None:
    workspace_dir = _make_workspace(tmp_path, ["repo-a"])
    target_wt = workspace_dir / "repositories" / "repo-a"
    target_wt.mkdir()

    def fake_run_git(path: Path, *args: str):
        result = type("R", (), {})()
        if args[:2] == ("rev-parse", "--git-common-dir"):
            result.returncode = 0
            result.stdout = "../../.git\n"
        else:
            result.returncode = 0
            result.stdout = ""
        return result

    with (
        patch("builtins.input", return_value="1"),
        patch.object(edit_workspace, "run_git", side_effect=fake_run_git),
        patch.object(edit_workspace, "update_workspace_agents"),
    ):
        edit_workspace.remove_repositories_from_workspace(workspace_dir)

    assert not target_wt.exists()


def test_main_not_inside_workspace_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "not-a-workspace"
    outside.mkdir()
    monkeypatch.setattr(edit_workspace, "find_project_root", lambda: outside)
    with pytest.raises(SystemExit) as exc:
        edit_workspace.main()
    assert exc.value.code == 1


def test_main_add_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_dir = tmp_path / "ws"
    (workspace_dir / "repositories").mkdir(parents=True)
    (workspace_dir / "config").mkdir()
    monkeypatch.setattr(edit_workspace, "find_project_root", lambda: workspace_dir)
    monkeypatch.delenv("AI_REPOSITORIES_DIR", raising=False)

    with (
        patch("builtins.input", return_value="1"),
        patch.object(edit_workspace, "add_repositories_to_workspace") as mock_add,
    ):
        edit_workspace.main()

    mock_add.assert_called_once()
    called_workspace_dir, called_repos_root = mock_add.call_args.args
    assert called_workspace_dir == workspace_dir
    assert called_repos_root == workspace_dir.parent.parent / "ai-repositories"


def test_main_add_option_with_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_dir = tmp_path / "ws"
    (workspace_dir / "repositories").mkdir(parents=True)
    (workspace_dir / "config").mkdir()
    repos_dir = tmp_path / "custom-repos"
    monkeypatch.setattr(edit_workspace, "find_project_root", lambda: workspace_dir)
    monkeypatch.setenv("AI_REPOSITORIES_DIR", str(repos_dir))

    with (
        patch("builtins.input", return_value="1"),
        patch.object(edit_workspace, "add_repositories_to_workspace") as mock_add,
    ):
        edit_workspace.main()

    called_repos_root = mock_add.call_args.args[1]
    assert called_repos_root == repos_dir.resolve()


def test_main_remove_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_dir = tmp_path / "ws"
    (workspace_dir / "repositories").mkdir(parents=True)
    (workspace_dir / "config").mkdir()
    monkeypatch.setattr(edit_workspace, "find_project_root", lambda: workspace_dir)

    with (
        patch("builtins.input", return_value="2"),
        patch.object(edit_workspace, "remove_repositories_from_workspace") as mock_remove,
    ):
        edit_workspace.main()

    mock_remove.assert_called_once_with(workspace_dir)


def test_main_invalid_option_cancels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_dir = tmp_path / "ws"
    (workspace_dir / "repositories").mkdir(parents=True)
    (workspace_dir / "config").mkdir()
    monkeypatch.setattr(edit_workspace, "find_project_root", lambda: workspace_dir)

    with patch("builtins.input", return_value="9"):
        edit_workspace.main()
