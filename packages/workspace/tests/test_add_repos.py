"""
Unit tests for workspace_engine.services.add_repos.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.services import add_repos
from workspace_engine.services.configure_repos import RepoConfig


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_setup_repo_worktree_already_exists(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    listing = _completed(stdout=f"worktree {target}\n")
    with patch.object(add_repos, "run_git", return_value=listing) as mock_git:
        add_repos.setup_repo_worktree(tmp_path, target, cfg)
    mock_git.assert_called_once()


def test_setup_repo_worktree_already_exists_among_multiple_lines(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    other = tmp_path / "other-wt"
    listing = _completed(stdout=f"worktree {other}\nbranch refs/heads/x\nworktree {target}\n")
    with patch.object(add_repos, "run_git", return_value=listing) as mock_git:
        add_repos.setup_repo_worktree(tmp_path, target, cfg)
    mock_git.assert_called_once()


def test_setup_repo_worktree_unknown_mode_is_a_noop(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="skip", branch="feature")

    def fake_git(repo_path, *args):
        return _completed(stdout="")

    with patch.object(add_repos, "run_git", side_effect=fake_git) as mock_git:
        add_repos.setup_repo_worktree(tmp_path, target, cfg)
    # Only the initial "worktree list" call happens; no add/fetch for an unknown mode.
    mock_git.assert_called_once()


def test_setup_repo_worktree_new_mode_uses_remote_ref(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")

    calls = []

    def fake_git(repo_path, *args):
        calls.append(args)
        if args[:2] == ("worktree", "list"):
            return _completed(stdout="")
        if args[:2] == ("rev-parse", "--verify"):
            return _completed(returncode=0)
        return _completed(returncode=0)

    with patch.object(add_repos, "run_git", side_effect=fake_git):
        add_repos.setup_repo_worktree(tmp_path, target, cfg)

    worktree_add_calls = [c for c in calls if c[:2] == ("worktree", "add")]
    assert worktree_add_calls
    assert "origin/main" in worktree_add_calls[0]


def test_setup_repo_worktree_new_mode_raises_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")

    def fake_git(repo_path, *args):
        if args[:2] == ("worktree", "add"):
            return _completed(returncode=1, stderr="boom")
        return _completed(returncode=0)

    with (
        patch.object(add_repos, "run_git", side_effect=fake_git),
        pytest.raises(RuntimeError, match="Failed to create worktree"),
    ):
        add_repos.setup_repo_worktree(tmp_path, target, cfg)


def test_setup_repo_worktree_existing_remote_only(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="existing", branch="feature")
    cfg.mark_remote_only()

    calls = []

    def fake_git(repo_path, *args):
        calls.append(args)
        return _completed(returncode=0)

    with patch.object(add_repos, "run_git", side_effect=fake_git):
        add_repos.setup_repo_worktree(tmp_path, target, cfg)

    assert any(c[:2] == ("worktree", "add") and "--track" in c for c in calls)


def test_setup_repo_worktree_existing_local_branch(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="existing", branch="feature")

    def fake_git(repo_path, *args):
        return _completed(returncode=0)

    with patch.object(add_repos, "run_git", side_effect=fake_git) as mock_git:
        add_repos.setup_repo_worktree(tmp_path, target, cfg)
    assert mock_git.call_count == 2  # listing + worktree add


def test_setup_repo_worktree_existing_raises_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "wt"
    cfg = RepoConfig(name="svc", mode="existing", branch="feature")

    def fake_git(repo_path, *args):
        if args[:2] == ("worktree", "add"):
            return _completed(returncode=1, stderr="boom")
        return _completed(returncode=0)

    with (
        patch.object(add_repos, "run_git", side_effect=fake_git),
        pytest.raises(RuntimeError, match="Failed to create worktree"),
    ):
        add_repos.setup_repo_worktree(tmp_path, target, cfg)


def _make_manifest(workspace_dir: Path, repos: list[str]) -> Path:
    manifest_dir = workspace_dir / ".ai-toolkit"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "workspace.json"
    manifest_path.write_text(
        json.dumps(
            {
                "workspace": "my-ws",
                "repositories": [{"name": r} for r in repos],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_add_repositories_no_manifest_exits(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    repos_root = tmp_path / "repos"
    with pytest.raises(SystemExit) as exc_info:
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)
    assert exc_info.value.code == 1


def test_add_repositories_selection_cancelled(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    _make_manifest(workspace_dir, [])
    repos_root = tmp_path / "repos"

    with (
        patch.object(add_repos, "select_repos", return_value=None),
        pytest.raises(SystemExit) as exc_info,
    ):
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)
    assert exc_info.value.code == 130


def test_add_repositories_retries_after_configure_repos_cancelled(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    manifest_path = _make_manifest(workspace_dir, [])
    repos_root = tmp_path / "repos"
    (repos_root / "svc").mkdir(parents=True)

    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    configure_calls = []

    def fake_configure(workspace_name, selected, repo_paths):
        configure_calls.append(list(selected))
        if len(configure_calls) == 1:
            return None
        return [cfg]

    with (
        patch.object(add_repos, "select_repos", return_value=["svc"]),
        patch.object(add_repos, "configure_repos", side_effect=fake_configure),
        patch.object(add_repos, "pre_validate", return_value=[]),
        patch.object(add_repos, "setup_repo_worktree", return_value=None),
        patch.object(add_repos, "update_workspace_agents", return_value=None),
    ):
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)

    assert len(configure_calls) == 2
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["repositories"] == [{"name": "svc", "branch": "feature", "parent_branch": "main"}]


def test_add_repositories_manifest_write_failure_exits(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    _make_manifest(workspace_dir, [])
    repos_root = tmp_path / "repos"
    (repos_root / "svc").mkdir(parents=True)

    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with (
        patch.object(add_repos, "select_repos", return_value=["svc"]),
        patch.object(add_repos, "configure_repos", return_value=[cfg]),
        patch.object(add_repos, "pre_validate", return_value=[]),
        patch.object(add_repos, "setup_repo_worktree", return_value=None),
        patch.object(
            add_repos.json,
            "loads",
            side_effect=[
                json.loads('{"workspace": "my-ws", "repositories": []}'),
                json.JSONDecodeError("corrupt manifest", "doc", 0),
            ],
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)
    assert exc_info.value.code == 1


def test_add_repositories_pre_validate_errors(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    _make_manifest(workspace_dir, [])
    repos_root = tmp_path / "repos"

    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with (
        patch.object(add_repos, "select_repos", return_value=["svc"]),
        patch.object(add_repos, "configure_repos", return_value=[cfg]),
        patch.object(add_repos, "pre_validate", return_value=["svc: some error"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)
    assert exc_info.value.code == 1


def test_add_repositories_full_success(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    manifest_path = _make_manifest(workspace_dir, [])
    repos_root = tmp_path / "repos"
    (repos_root / "svc").mkdir(parents=True)

    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with (
        patch.object(add_repos, "select_repos", return_value=["svc"]),
        patch.object(add_repos, "configure_repos", return_value=[cfg]),
        patch.object(add_repos, "pre_validate", return_value=[]),
        patch.object(add_repos, "setup_repo_worktree", return_value=None),
        patch.object(add_repos, "update_workspace_agents", return_value=None),
    ):
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["repositories"] == [{"name": "svc", "branch": "feature", "parent_branch": "main"}]


def test_add_repositories_worktree_failure_all_fail_exits(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    _make_manifest(workspace_dir, [])
    repos_root = tmp_path / "repos"

    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with (
        patch.object(add_repos, "select_repos", return_value=["svc"]),
        patch.object(add_repos, "configure_repos", return_value=[cfg]),
        patch.object(add_repos, "pre_validate", return_value=[]),
        patch.object(add_repos, "setup_repo_worktree", side_effect=RuntimeError("boom")),
        pytest.raises(SystemExit) as exc_info,
    ):
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)
    assert exc_info.value.code == 1


def test_add_repositories_agents_update_failure_warns_but_succeeds(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    _make_manifest(workspace_dir, [])
    repos_root = tmp_path / "repos"
    (repos_root / "svc").mkdir(parents=True)

    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with (
        patch.object(add_repos, "select_repos", return_value=["svc"]),
        patch.object(add_repos, "configure_repos", return_value=[cfg]),
        patch.object(add_repos, "pre_validate", return_value=[]),
        patch.object(add_repos, "setup_repo_worktree", return_value=None),
        patch.object(add_repos, "update_workspace_agents", side_effect=OSError("no perms")),
    ):
        # Should not raise even though updating AGENTS.md fails.
        add_repos.add_repositories_to_workspace(workspace_dir, repos_root)


def test_main_missing_repos_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    monkeypatch.delenv("AI_REPOSITORIES_DIR", raising=False)
    with (
        patch("sys.argv", ["add_repos.py", "--workspace-dir", str(workspace_dir)]),
        pytest.raises(SystemExit) as exc_info,
    ):
        add_repos.main()
    assert exc_info.value.code == 1


def test_main_repos_dir_from_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    repos_dir = tmp_path / "env-repos"
    repos_dir.mkdir()
    monkeypatch.setenv("AI_REPOSITORIES_DIR", str(repos_dir))
    with (
        patch("sys.argv", ["add_repos.py", "--workspace-dir", str(workspace_dir)]),
        patch.object(add_repos, "add_repositories_to_workspace") as mock_add,
    ):
        add_repos.main()
    mock_add.assert_called_once()
    _called_workspace_dir, called_repos_dir = mock_add.call_args[0]
    assert called_repos_dir == repos_dir.resolve()


def test_main_with_repos_dir_arg(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    with (
        patch(
            "sys.argv",
            [
                "add_repos.py",
                "--workspace-dir",
                str(workspace_dir),
                "--repos-dir",
                str(repos_dir),
            ],
        ),
        patch.object(add_repos, "add_repositories_to_workspace") as mock_add,
    ):
        add_repos.main()
    mock_add.assert_called_once()
    called_workspace_dir, called_repos_dir = mock_add.call_args[0]
    assert called_workspace_dir == workspace_dir.resolve()
    assert called_repos_dir == repos_dir.resolve()
