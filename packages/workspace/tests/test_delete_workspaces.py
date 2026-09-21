"""
Unit tests for workspace_engine.cli.delete_workspaces.

All filesystem effects happen under tmp_path; git and confirmation prompts
are mocked so no real subprocess or terminal interaction happens.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.cli import delete_workspaces as dw


def _git_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    res = MagicMock()
    res.returncode = returncode
    res.stdout = stdout
    res.stderr = stderr
    return res


# ---------------------------------------------------------------------------
# _is_owned_workspace
# ---------------------------------------------------------------------------


def test_is_owned_workspace_metadata_marker(tmp_path: Path) -> None:
    (tmp_path / ".workspace_metadata").write_text("x")
    assert dw._is_owned_workspace(tmp_path) is True


def test_is_owned_workspace_ai_toolkit_dir(tmp_path: Path) -> None:
    (tmp_path / ".ai-toolkit").mkdir()
    assert dw._is_owned_workspace(tmp_path) is True


def test_is_owned_workspace_git_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /somewhere")
    assert dw._is_owned_workspace(tmp_path) is True


def test_is_owned_workspace_repositories_with_git_subdir(tmp_path: Path) -> None:
    repo = tmp_path / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    assert dw._is_owned_workspace(tmp_path) is True


def test_is_owned_workspace_unowned(tmp_path: Path) -> None:
    (tmp_path / "somefile.txt").write_text("x")
    assert dw._is_owned_workspace(tmp_path) is False


def test_is_owned_workspace_repositories_dir_without_git_subdirs(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "not-a-dir.txt").write_text("x")
    (repos_dir / "plain-dir").mkdir()
    assert dw._is_owned_workspace(tmp_path) is False


# ---------------------------------------------------------------------------
# _has_dirty_repos
# ---------------------------------------------------------------------------


def test_has_dirty_repos_reports_dirty_subrepo_and_root(tmp_path: Path) -> None:
    repo = tmp_path / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (tmp_path / ".git").mkdir()

    with patch(
        "workspace_engine.cli.delete_workspaces.run_git",
        side_effect=[
            _git_result(stdout=" M file.txt\n"),
            _git_result(stdout=" M other.txt\n"),
        ],
    ):
        dirty = dw._has_dirty_repos(tmp_path)
    assert set(dirty) == {"repo-a", tmp_path.name}


def test_has_dirty_repos_clean(tmp_path: Path) -> None:
    repo = tmp_path / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()

    with patch(
        "workspace_engine.cli.delete_workspaces.run_git", return_value=_git_result(stdout="")
    ):
        assert dw._has_dirty_repos(tmp_path) == []


def test_has_dirty_repos_no_repositories_dir(tmp_path: Path) -> None:
    assert dw._has_dirty_repos(tmp_path) == []


def test_has_dirty_repos_skips_non_git_entries_and_clean_root(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "not-a-repo.txt").write_text("x")
    repo = repos_dir / "repo-a"
    repo.mkdir()
    (repo / ".git").mkdir()
    (tmp_path / ".git").mkdir()

    with patch(
        "workspace_engine.cli.delete_workspaces.run_git", return_value=_git_result(stdout="")
    ):
        dirty = dw._has_dirty_repos(tmp_path)
    assert dirty == []


# ---------------------------------------------------------------------------
# delete_single_workspace
# ---------------------------------------------------------------------------


def test_delete_single_workspace_escapes_base_dir_raises(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    base_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="escapes managed workspaces directory"):
        dw.delete_single_workspace(outside, workspaces_dir=base_dir)


def test_delete_single_workspace_not_a_dir(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    base_dir.mkdir()
    target = base_dir / "missing-ws"
    assert dw.delete_single_workspace(target, workspaces_dir=base_dir) is False


def test_delete_single_workspace_not_owned_raises(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    target.mkdir(parents=True)
    with pytest.raises(ValueError, match="not an owned workspace"):
        dw.delete_single_workspace(target, workspaces_dir=base_dir)


def test_delete_single_workspace_default_workspaces_dir_uses_project_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    ws_dir = root / "workspaces"
    target = ws_dir / "ws-a"
    target.mkdir(parents=True)
    (target / ".workspace_metadata").write_text("x")

    with patch("workspace_engine.cli.delete_workspaces.find_project_root", return_value=root):
        ok = dw.delete_single_workspace(target)
    assert ok is True
    assert not target.exists()


def test_delete_single_workspace_dirty_without_force_returns_false(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repo = target / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (target / ".workspace_metadata").write_text("x")

    with patch(
        "workspace_engine.cli.delete_workspaces.run_git",
        return_value=_git_result(stdout=" M dirty.txt\n"),
    ):
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is False


def test_delete_single_workspace_dirty_with_force_proceeds(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repo = target / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (target / ".workspace_metadata").write_text("x")

    with patch(
        "workspace_engine.cli.delete_workspaces.run_git",
        return_value=_git_result(stdout=" M dirty.txt\n"),
    ):
        ok = dw.delete_single_workspace(target, force=True, workspaces_dir=base_dir)
    assert ok is True
    assert not target.exists()


def test_delete_single_workspace_removes_linked_worktree(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repo = target / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: /elsewhere")  # linked worktree marker (file, not dir)
    common_dir = tmp_path / "bare-common"
    common_dir.mkdir()

    calls = {"prune": False}

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("rev-parse", "--git-common-dir"):
            return _git_result(stdout=str(common_dir) + "\n")
        if args[:2] == ("worktree", "remove"):
            return _git_result(returncode=0)
        if args[:2] == ("worktree", "prune"):
            calls["prune"] = True
            return _git_result(returncode=0)
        if args[0] == "status":
            return _git_result(stdout="")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.delete_workspaces.run_git", side_effect=fake_run_git):
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is True
    assert calls["prune"] is True


def test_delete_single_workspace_worktree_remove_failure_returns_false(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repo = target / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: /elsewhere")
    common_dir = tmp_path / "bare-common"
    common_dir.mkdir()

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("rev-parse", "--git-common-dir"):
            return _git_result(stdout=str(common_dir) + "\n")
        if args[:2] == ("worktree", "remove"):
            return _git_result(returncode=1, stderr="fatal: locked working tree")
        if args[0] == "status":
            return _git_result(stdout="")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.delete_workspaces.run_git", side_effect=fake_run_git):
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is False
    assert target.exists()  # deletion never attempted


def test_delete_single_workspace_worktree_is_main_working_tree_continues(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repo = target / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: /elsewhere")
    common_dir = tmp_path / "bare-common"
    common_dir.mkdir()

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("rev-parse", "--git-common-dir"):
            return _git_result(stdout=str(common_dir) + "\n")
        if args[:2] == ("worktree", "remove"):
            return _git_result(returncode=1, stderr="fatal: 'repo-a' is a main working tree")
        if args[:2] == ("worktree", "prune"):
            return _git_result(returncode=0)
        if args[0] == "status":
            return _git_result(stdout="")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.delete_workspaces.run_git", side_effect=fake_run_git):
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is True
    assert not target.exists()


def test_delete_single_workspace_git_common_dir_lookup_fails_skips_removal(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repo = target / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()  # regular (non-worktree) repo dir

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("rev-parse", "--git-common-dir"):
            return _git_result(returncode=1, stdout="")
        if args[0] == "status":
            return _git_result(stdout="")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.delete_workspaces.run_git", side_effect=fake_run_git):
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is True
    assert not target.exists()


def test_delete_single_workspace_skips_non_git_repo_entries(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repos_dir = target / "repositories"
    repos_dir.mkdir(parents=True)
    (repos_dir / "not-a-repo.txt").write_text("x")
    (target / ".workspace_metadata").write_text("x")

    ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is True
    assert not target.exists()


def test_delete_single_workspace_common_path_matches_repo_git_skips_remove(
    tmp_path: Path,
) -> None:
    """When the resolved git-common-dir points back at the repo's own .git
    (i.e. it is not actually a linked worktree), `worktree remove` must not
    be invoked."""
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    repo = target / "repositories" / "repo-a"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()  # not a worktree (dir, not file)
    (target / ".workspace_metadata").write_text("x")

    own_git_dir = (repo / ".git").resolve()

    def fake_run_git(path: Path, *args: str) -> MagicMock:
        if args[:2] == ("rev-parse", "--git-common-dir"):
            return _git_result(stdout=str(own_git_dir) + "\n")
        if args[0] == "status":
            return _git_result(stdout="")
        raise AssertionError(f"unexpected git call: {args}")

    with patch("workspace_engine.cli.delete_workspaces.run_git", side_effect=fake_run_git):
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is True
    assert not target.exists()


def test_delete_single_workspace_rmtree_oserror_returns_false(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    target.mkdir(parents=True)
    (target / ".workspace_metadata").write_text("x")

    with patch(
        "workspace_engine.cli.delete_workspaces.shutil.rmtree",
        side_effect=OSError("permission denied"),
    ):
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is False


def test_delete_single_workspace_still_exists_after_rmtree_returns_false(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    target.mkdir(parents=True)
    (target / ".workspace_metadata").write_text("x")

    with patch("workspace_engine.cli.delete_workspaces.shutil.rmtree"):  # no-op, dir stays
        ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is False


def test_delete_single_workspace_success(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspaces"
    target = base_dir / "ws-a"
    target.mkdir(parents=True)
    (target / ".workspace_metadata").write_text("x")

    ok = dw.delete_single_workspace(target, workspaces_dir=base_dir)
    assert ok is True
    assert not target.exists()


# ---------------------------------------------------------------------------
# delete_workspaces
# ---------------------------------------------------------------------------


def test_delete_workspaces_inside_current_workspace_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ws-current"
    (root / "repositories").mkdir(parents=True)
    (root / ".workspace_metadata").write_text("x")

    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "y")
    with patch.object(dw, "delete_single_workspace", return_value=True) as mock_del:
        rc = dw.delete_workspaces()
    assert rc == 0
    mock_del.assert_called_once_with(root, force=True, workspaces_dir=None)


def test_delete_workspaces_inside_current_workspace_declined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ws-current"
    (root / "repositories").mkdir(parents=True)
    (root / ".workspace_metadata").write_text("x")

    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "n")
    with patch.object(dw, "delete_single_workspace") as mock_del:
        rc = dw.delete_workspaces()
    assert rc == 0
    mock_del.assert_not_called()


def test_delete_workspaces_inside_current_workspace_force_skips_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ws-current"
    (root / "repositories").mkdir(parents=True)
    (root / ".workspace_metadata").write_text("x")

    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    with patch.object(dw, "delete_single_workspace", return_value=False) as mock_del:
        rc = dw.delete_workspaces(force=True)
    assert rc == 1
    mock_del.assert_called_once_with(root, force=True, workspaces_dir=None)


def test_delete_workspaces_root_missing_returns_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()
    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    rc = dw.delete_workspaces(workspaces_dir=tmp_path / "does-not-exist")
    assert rc == 0


def test_delete_workspaces_no_available_workspaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    rc = dw.delete_workspaces(workspaces_dir=ws_root)
    assert rc == 0


def test_delete_workspaces_interactive_selection_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()
    ws_root = tmp_path / "workspaces"
    (ws_root / "ws-a").mkdir(parents=True)
    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "q")
    rc = dw.delete_workspaces(workspaces_dir=ws_root)
    assert rc == 0


def test_delete_workspaces_interactive_selection_picks_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()
    ws_root = tmp_path / "workspaces"
    (ws_root / "ws-a").mkdir(parents=True)
    (ws_root / "ws-b").mkdir(parents=True)
    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "1")
    with patch.object(dw, "delete_single_workspace", return_value=True) as mock_del:
        rc = dw.delete_workspaces(workspaces_dir=ws_root)
    assert rc == 0
    mock_del.assert_called_once()


def test_delete_workspaces_direct_list_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    with patch.object(dw, "delete_single_workspace", return_value=True) as mock_del:
        rc = dw.delete_workspaces(workspaces=["ws-a"], workspaces_dir=ws_root)
    assert rc == 0
    mock_del.assert_called_once()


def test_delete_workspaces_direct_list_failure_stops_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr(dw, "find_project_root", lambda: root)
    with patch.object(dw, "delete_single_workspace", return_value=False):
        rc = dw.delete_workspaces(workspaces=["ws-a", "ws-b"], workspaces_dir=ws_root)
    assert rc == 1


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_forwards_args_and_exit_code() -> None:
    with (
        patch("sys.argv", ["delete-workspaces", "ws-a", "--force"]),
        patch.object(dw, "delete_workspaces", return_value=0) as mock_dw,
        pytest.raises(SystemExit) as exc,
    ):
        dw.main()
    assert exc.value.code == 0
    mock_dw.assert_called_once_with(workspaces=["ws-a"], force=True)


def test_main_value_error_exits_1() -> None:
    with (
        patch("sys.argv", ["delete-workspaces"]),
        patch.object(dw, "delete_workspaces", side_effect=ValueError("boom")),
        pytest.raises(SystemExit) as exc,
    ):
        dw.main()
    assert exc.value.code == 1
