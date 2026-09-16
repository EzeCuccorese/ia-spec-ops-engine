"""
Unit tests for workspace_engine.services.configure_repos: branch discovery, worktree
parsing, pre-validation, and the interactive TUI panels (driven with a fake tty and
mocked keypresses so no real terminal is required).
"""

from __future__ import annotations

import builtins
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.services import configure_repos as cr
from workspace_engine.services.configure_repos import (
    RepoConfig,
    _confirm_panel,
    _parse_worktrees,
    configure_repos,
    fetch_branches,
    pre_validate,
)


class FakeTty:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def fileno(self) -> int:
        return 42

    def close(self) -> None:
        self.closed = True


def test_fetch_branches_dedups_and_sorts(tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="main\nremotes/origin/main\norigin/feature-b\nfeature-a\nHEAD\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=completed) as mock_run:
        branches = fetch_branches(tmp_path, skip_fetch=True)
    assert branches == ["feature-a", "feature-b", "main"]
    # skip_fetch=True: only one subprocess.run call (branch -a), no fetch call.
    assert mock_run.call_count == 1


def test_fetch_branches_runs_fetch_when_not_skipped(tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="main\n", stderr="")
    with patch("subprocess.run", return_value=completed) as mock_run:
        fetch_branches(tmp_path, skip_fetch=False)
    assert mock_run.call_count == 2
    fetch_call_args = mock_run.call_args_list[0][0][0]
    assert "fetch" in fetch_call_args


def test_parse_worktrees() -> None:
    porcelain = (
        "worktree /repo\nbranch refs/heads/main\n\nworktree /repo-wt\nbranch refs/heads/feature\n\n"
    )
    result = _parse_worktrees(porcelain)
    assert result == [
        (Path("/repo"), "refs/heads/main"),
        (Path("/repo-wt"), "refs/heads/feature"),
    ]


def test_parse_worktrees_empty() -> None:
    assert _parse_worktrees("") == []


def test_pre_validate_missing_repo_dir(tmp_path: Path) -> None:
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    errors = pre_validate([cfg], {})
    assert len(errors) == 1
    assert "repository directory not found" in errors[0]


def test_pre_validate_existing_branch_active_elsewhere(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="existing", branch="feature")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "list"):
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=0,
                stdout="worktree /other\nbranch refs/heads/feature\n\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with patch.object(cr, "_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert any("already active in another worktree" in e for e in errors)


def test_pre_validate_existing_branch_remote_only(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="existing", branch="feature")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "list"):
            return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")
        if "refs/heads/feature" in args:
            return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="")
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with patch.object(cr, "_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert errors == []
    assert cfg.is_remote_only is True


def test_pre_validate_new_missing_parent(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="develop")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="")

    with patch.object(cr, "_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert any("does not exist locally or on origin" in e for e in errors)


def test_pre_validate_new_parent_ok(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="develop")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with patch.object(cr, "_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert errors == []


def test_branch_config_panel_new_mode_confirm(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    fake_fd = FakeTty()
    with patch.object(cr, "_read_key", side_effect=[b"\x1b[B", b"\x1b[B", b"\r"]):
        cfg = cr._branch_config_panel(
            repo_name="svc",
            workspace_name="feature-x",
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
            pre_fetch_cache={"svc": []},
        )
    assert cfg == RepoConfig(name="svc", mode="new", branch="feature-x", parent="main")


def test_branch_config_panel_esc_cancels(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    fake_fd = FakeTty()
    with patch.object(cr, "_read_key", side_effect=[b"\x1b"]):
        cfg = cr._branch_config_panel(
            repo_name="svc",
            workspace_name="feature-x",
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
            pre_fetch_cache={"svc": []},
        )
    assert cfg is None


def test_branch_config_panel_existing_mode_pick_branch(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    fake_fd = FakeTty()
    keys = [
        b"\x1b[D",  # switch to "existing" mode
        b"\r",  # enter editing (opens picker)
        b"\x1b[B",  # move to first suggestion
        b"\r",  # select suggestion
        b"\x1b[B",  # move focus to confirm
        b"\r",  # confirm
    ]
    with patch.object(cr, "_read_key", side_effect=keys):
        cfg = cr._branch_config_panel(
            repo_name="svc",
            workspace_name="feature-x",
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
            pre_fetch_cache={"svc": ["develop", "main"]},
        )
    assert cfg == RepoConfig(name="svc", mode="existing", branch="develop", parent=None)


def test_branch_config_panel_name_error_when_branch_exists(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    fake_fd = FakeTty()
    # workspace_name collides with an existing branch -> name_error is pre-set;
    # confirm attempt at the confirm row should re-set the error and refocus.
    with patch.object(cr, "_read_key", side_effect=[b"\x1b[B", b"\x1b[B", b"\r", b"\x1b"]):
        cfg = cr._branch_config_panel(
            repo_name="svc",
            workspace_name="feature-x",
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
            pre_fetch_cache={"svc": ["feature-x"]},
        )
    assert cfg is None


def test_confirm_panel_confirm_and_back() -> None:
    fake_fd = FakeTty()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with patch.object(cr, "_read_key", side_effect=[b"\r"]):
        assert _confirm_panel([cfg], fake_fd, None) is True

    fake_fd2 = FakeTty()
    with patch.object(cr, "_read_key", side_effect=[b"\x1b"]):
        assert _confirm_panel([cfg], fake_fd2, None) is False


def test_confirm_panel_existing_branch_row() -> None:
    fake_fd = FakeTty()
    cfg = RepoConfig(name="svc", mode="existing", branch="develop")
    with patch.object(cr, "_read_key", side_effect=[b"\r"]):
        assert _confirm_panel([cfg], fake_fd, None) is True


def test_configure_repos_empty_repo_names() -> None:
    assert configure_repos("ws", [], {}) == []


def test_configure_repos_no_tty_fallback(tmp_path: Path) -> None:
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/dev/tty":
            raise OSError("no tty available")
        return real_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=fake_open):
        result = configure_repos("ws", ["svc"], {"svc": tmp_path})
    assert result == [RepoConfig(name="svc", mode="new", branch="ws", parent="main")]


def test_configure_repos_interactive_confirmed(tmp_path: Path) -> None:
    fake_fd = FakeTty()
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/dev/tty":
            return fake_fd
        return real_open(path, *args, **kwargs)

    produced_cfg = RepoConfig(name="svc", mode="new", branch="ws", parent="main")

    with (
        patch("builtins.open", side_effect=fake_open),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(cr, "_branch_config_panel", return_value=produced_cfg),
        patch.object(cr, "_confirm_panel", return_value=True),
        patch.object(cr, "pre_validate", return_value=[]),
    ):
        result = configure_repos("ws", ["svc"], {"svc": tmp_path})
    assert result == [produced_cfg]
    assert fake_fd.closed is True


def test_configure_repos_first_panel_cancelled(tmp_path: Path) -> None:
    fake_fd = FakeTty()
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/dev/tty":
            return fake_fd
        return real_open(path, *args, **kwargs)

    with (
        patch("builtins.open", side_effect=fake_open),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(cr, "_branch_config_panel", return_value=None),
    ):
        result = configure_repos("ws", ["svc"], {"svc": tmp_path})
    assert result is None


def test_configure_repos_confirm_panel_declines_then_reconfigures(tmp_path: Path) -> None:
    fake_fd = FakeTty()
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/dev/tty":
            return fake_fd
        return real_open(path, *args, **kwargs)

    produced_cfg = RepoConfig(name="svc", mode="new", branch="ws", parent="main")

    with (
        patch("builtins.open", side_effect=fake_open),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(cr, "_branch_config_panel", return_value=produced_cfg),
        patch.object(cr, "_confirm_panel", side_effect=[False, True]),
        patch.object(cr, "pre_validate", return_value=[]),
    ):
        result = configure_repos("ws", ["svc"], {"svc": tmp_path})
    assert result == [produced_cfg]


def test_configure_repos_pre_validate_errors_exit(tmp_path: Path) -> None:
    fake_fd = FakeTty()
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/dev/tty":
            return fake_fd
        return real_open(path, *args, **kwargs)

    produced_cfg = RepoConfig(name="svc", mode="new", branch="ws", parent="main")

    with (
        patch("builtins.open", side_effect=fake_open),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(cr, "_branch_config_panel", return_value=produced_cfg),
        patch.object(cr, "_confirm_panel", return_value=True),
        patch.object(cr, "pre_validate", return_value=["svc: some error"]),
        pytest.raises(SystemExit),
    ):
        configure_repos("ws", ["svc"], {"svc": tmp_path})


def test_tty_write_encodes() -> None:
    fake_fd = FakeTty()
    cr._tty_write(fake_fd, "hello")
    assert fake_fd.written == [b"hello"]


def test_git_delegates_to_run_git(tmp_path: Path) -> None:
    with patch.object(cr, "run_git", return_value=MagicMock()) as mock_run_git:
        cr._git(tmp_path, "status")
    mock_run_git.assert_called_once_with(tmp_path, "status")
