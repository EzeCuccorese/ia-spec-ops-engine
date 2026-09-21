"""
Unit tests for workspace_engine.services.configure_repos: branch discovery, worktree
parsing, pre-validation, and the interactive TUI panels (driven with a fake tty and
mocked keypresses so no real terminal is required).
"""

from __future__ import annotations

import builtins
import subprocess
from pathlib import Path
from unittest.mock import patch

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

    with patch.object(cr, "run_git", side_effect=fake_git):
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

    with patch.object(cr, "run_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert errors == []
    assert cfg.is_remote_only is True


def test_pre_validate_new_missing_parent(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="develop")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="")

    with patch.object(cr, "run_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert any("does not exist locally or on origin" in e for e in errors)


def test_pre_validate_new_parent_ok(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="develop")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with patch.object(cr, "run_git", side_effect=fake_git):
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


def test_branch_config_panel_ctrl_c_exits(tmp_path: Path) -> None:
    with (
        patch("termios.tcsetattr") as mock_set,
        pytest.raises(SystemExit) as exc_info,
    ):
        _panel(tmp_path, [b"\x03"])
    assert exc_info.value.code == 130
    mock_set.assert_called_once()


def test_branch_config_panel_new_name_cursor_arrows(tmp_path: Path) -> None:
    # Open the name field, move the cursor left/right while editing, submit it,
    # then cancel from the (now unfocused) parent field.
    cfg = _panel(
        tmp_path,
        [b"\r", b"\x1b[D", b"\x1b[C", b"\r", b"\x1b"],
    )
    assert cfg is None


def test_branch_config_panel_new_parent_picker_cursor_arrows(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\r", b"\r", b"\x1b[D", b"\x1b[C", b"\x1b", b"\x1b"],
        branches=["main", "develop"],
    )
    assert cfg is None


def test_branch_config_panel_existing_filter_cursor_arrows(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"\x1b[D", b"\x1b[C", b"\x1b", b"\x1b"],
        branches=["main", "develop"],
    )
    assert cfg is None


def test_branch_config_panel_mode_toggle_round_trip(tmp_path: Path) -> None:
    # new -> existing -> new, then cancel.
    cfg = _panel(tmp_path, [b"\x1b[D", b"\x1b[C", b"\x1b"])
    assert cfg is None


def test_branch_config_panel_home_end_new_name(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\x1b[H", b"\x1b[F", b"\x1b[1~", b"\x1b[4~", b"\x1b", b"\x1b"],
    )
    assert cfg is None


def test_branch_config_panel_home_end_parent_filter(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [
            b"\r",
            b"\r",
            b"\r",
            b"\x1b[H",
            b"\x1b[F",
            b"\x1b[1~",
            b"\x1b[4~",
            b"\x1b",
            b"\x1b",
        ],
        branches=["main"],
    )
    assert cfg is None


def test_branch_config_panel_home_end_existing_filter(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [
            b"\x1b[D",
            b"\r",
            b"\x1b[H",
            b"\x1b[F",
            b"\x1b[1~",
            b"\x1b[4~",
            b"\x1b",
            b"\x1b",
        ],
        branches=["main"],
    )
    assert cfg is None


def test_branch_config_panel_delete_key_new_name(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [
            b"\r",  # edit name (default text = workspace_name, cursor at end)
            b"\x1b[H",  # move cursor to start (now < len(name))
            b"\x1b[3~",  # delete first character
            b"\x1b[F",  # move to end
            b"\x1b[3~",  # delete at end is a no-op (cursor == len)
            b"\x1b",
            b"\x1b",
        ],
        workspace_name="feat",
    )
    assert cfg is None


def test_branch_config_panel_delete_key_parent_filter(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [
            b"\r",
            b"\r",
            b"\r",  # open parent picker (filter empty)
            b"a",  # type a char
            b"\x1b[H",
            b"\x1b[3~",  # delete it
            b"\x1b",
            b"\x1b",
        ],
        branches=["main"],
    )
    assert cfg is None


def test_branch_config_panel_delete_key_existing_filter(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [
            b"\x1b[D",
            b"\r",
            b"m",
            b"\x1b[H",
            b"\x1b[3~",
            b"\x1b",
            b"\x1b",
        ],
        branches=["main"],
    )
    assert cfg is None


def test_branch_config_panel_backspace_new_name(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\x7f", b"\x1b", b"\x1b"],
        workspace_name="feat",
    )
    assert cfg is None


def test_branch_config_panel_backspace_parent_filter(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\r", b"\r", b"a", b"\x7f", b"\x1b", b"\x1b"],
        branches=["main"],
    )
    assert cfg is None


def test_branch_config_panel_backspace_existing_filter(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"m", b"\x7f", b"\x1b", b"\x1b"],
        branches=["main"],
    )
    assert cfg is None


def test_branch_config_panel_unmapped_key_while_not_editing_is_noop(tmp_path: Path) -> None:
    cfg = _panel(tmp_path, [b"x", b"\x1b"])
    assert cfg is None


def test_branch_config_panel_name_empty_error_on_confirm(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[B", b"\x1b[B", b"\r", b"\x1b"],
        workspace_name="",
    )
    assert cfg is None


def test_branch_config_panel_existing_confirm_without_branch_selected(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\x1b[B", b"\r", b"\x1b"],
        branches=["main"],
    )
    assert cfg is None


def test_branch_config_panel_parent_dropdown_selection(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\r", b"\r", b"\x1b[B", b"\r", b"\r"],
        workspace_name="feat",
        branches=["alpha", "beta"],
    )
    assert cfg == RepoConfig(name="svc", mode="new", branch="feat", parent="alpha")


def test_branch_config_panel_parent_typed_exact_match(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\r", b"\r", b"a", b"l", b"p", b"h", b"a", b"\r", b"\r"],
        workspace_name="feat",
        branches=["alpha", "beta"],
    )
    assert cfg == RepoConfig(name="svc", mode="new", branch="feat", parent="alpha")


def test_branch_config_panel_parent_typed_no_match_stays_in_picker(tmp_path: Path) -> None:
    # Typing text that matches no branch keeps the picker open (Enter is a no-op);
    # ESC out of editing then cancel the whole panel.
    cfg = _panel(
        tmp_path,
        [b"\r", b"\r", b"\r", b"z", b"z", b"z", b"\r", b"\x1b", b"\x1b"],
        workspace_name="feat",
        branches=["alpha", "beta"],
    )
    assert cfg is None


def test_branch_config_panel_existing_dropdown_selection(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"\x1b[B", b"\r", b"\x1b[B", b"\r"],
        branches=["alpha", "beta"],
    )
    assert cfg == RepoConfig(name="svc", mode="existing", branch="alpha", parent=None)


def test_branch_config_panel_existing_typed_no_match_sets_error(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"z", b"z", b"z", b"\r", b"\x1b", b"\x1b"],
        branches=["alpha", "beta"],
    )
    assert cfg is None


def test_branch_config_panel_dropdown_up_navigation(tmp_path: Path) -> None:
    # Move down twice in the dropdown (idx 0, 1), then up twice: idx 1 -> 0 -> -1.
    cfg = _panel(
        tmp_path,
        [
            b"\x1b[D",
            b"\r",
            b"\x1b[B",
            b"\x1b[B",
            b"\x1b[A",
            b"\x1b[A",
            b"\x1b",
            b"\x1b",
        ],
        branches=["alpha", "beta", "gamma"],
    )
    assert cfg is None


def test_branch_config_panel_up_arrow_not_editing_moves_focus(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[B", b"\x1b[A", b"\x1b"],
    )
    assert cfg is None


def test_branch_config_panel_down_arrow_dropdown_empty_suggestions(tmp_path: Path) -> None:
    # Open the existing-branch picker with no branches available: Down arrow in
    # the dropdown has nothing to select.
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"\x1b[B", b"\x1b", b"\x1b"],
        branches=[],
    )
    assert cfg is None


def test_configure_repos_prefetch_error_is_caught(tmp_path: Path) -> None:
    import threading as _threading

    fake_fd = FakeTty()
    real_open = builtins.open
    called = _threading.Event()

    def fake_open(path, *args, **kwargs):
        if str(path) == "/dev/tty":
            return fake_fd
        return real_open(path, *args, **kwargs)

    def failing_fetch(*args, **kwargs):
        called.set()
        raise OSError("boom")

    produced_cfg = RepoConfig(name="svc", mode="new", branch="ws", parent="main")

    with (
        patch("builtins.open", side_effect=fake_open),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        # fetch_branches raising inside the background prefetch thread is caught
        # by _prefetch's except clause. The panel patch below blocks until the
        # background thread has actually invoked (and failed) fetch_branches,
        # so the assertion isn't racing the daemon thread.
        patch.object(cr, "fetch_branches", side_effect=failing_fetch),
        patch.object(
            cr,
            "_branch_config_panel",
            side_effect=lambda **kw: (called.wait(timeout=2), produced_cfg)[1],
        ),
        patch.object(cr, "_confirm_panel", return_value=True),
        patch.object(cr, "pre_validate", return_value=[]),
    ):
        result = cr.configure_repos("ws", ["svc"], {"svc": tmp_path})
    assert result == [produced_cfg]
    assert called.is_set()


def test_configure_repos_second_panel_cancel_goes_back(tmp_path: Path) -> None:
    fake_fd = FakeTty()
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/dev/tty":
            return fake_fd
        return real_open(path, *args, **kwargs)

    cfg_a = RepoConfig(name="a", mode="new", branch="ws", parent="main")
    cfg_b = RepoConfig(name="b", mode="new", branch="ws", parent="main")

    with (
        patch("builtins.open", side_effect=fake_open),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(cr, "_branch_config_panel", side_effect=[cfg_a, None, cfg_a, cfg_b]),
        patch.object(cr, "_confirm_panel", return_value=True),
        patch.object(cr, "pre_validate", return_value=[]),
    ):
        result = configure_repos("ws", ["a", "b"], {"a": tmp_path, "b": tmp_path})
    assert result == [cfg_a, cfg_b]


def test_branch_config_panel_fetches_fresh_when_no_prefetch_cache(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    git_dir = repo_path / ".git"
    git_dir.mkdir()
    (git_dir / "FETCH_HEAD").write_text("x")
    fake_fd = FakeTty()
    with (
        patch.object(cr, "_read_key", side_effect=[b"\x1b"]),
        patch.object(cr, "fetch_branches", return_value=["main"]) as mock_fetch,
    ):
        cfg = cr._branch_config_panel(
            repo_name="svc",
            workspace_name="feat",
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
        )
    assert cfg is None
    mock_fetch.assert_called_once_with(repo_path, skip_fetch=True)


def test_branch_config_panel_fetches_stale_when_no_fetch_head(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    fake_fd = FakeTty()
    with (
        patch.object(cr, "_read_key", side_effect=[b"\x1b"]),
        patch.object(cr, "fetch_branches", return_value=["main"]) as mock_fetch,
    ):
        cfg = cr._branch_config_panel(
            repo_name="svc",
            workspace_name="feat",
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
        )
    assert cfg is None
    mock_fetch.assert_called_once_with(repo_path, skip_fetch=False)


def test_branch_config_panel_shows_last_fetched_timestamp(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    git_dir = repo_path / ".git"
    git_dir.mkdir()
    (git_dir / "FETCH_HEAD").write_text("x")
    fake_fd = FakeTty()
    with patch.object(cr, "_read_key", side_effect=[b"\x1b"]):
        cfg = cr._branch_config_panel(
            repo_name="svc",
            workspace_name="feat",
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
            pre_fetch_cache={"svc": []},
        )
    assert cfg is None
    rendered = b"".join(fake_fd.written).decode(errors="ignore")
    assert "updated:" in rendered


def test_branch_config_panel_non_editing_keys_are_noop(tmp_path: Path) -> None:
    # Home/End/Delete/Backspace pressed while not editing do nothing.
    cfg = _panel(
        tmp_path,
        [b"\x1b[H", b"\x1b[F", b"\x1b[3~", b"\x7f", b"\x1b"],
    )
    assert cfg is None


def test_branch_config_panel_up_arrow_not_editing_at_top_is_noop(tmp_path: Path) -> None:
    cfg = _panel(tmp_path, [b"\x1b[A", b"\x1b"])
    assert cfg is None


def test_branch_config_panel_down_arrow_while_editing_name_is_noop(tmp_path: Path) -> None:
    cfg = _panel(tmp_path, [b"\r", b"\x1b[B", b"\x1b", b"\x1b"])
    assert cfg is None


def test_branch_config_panel_down_arrow_dropdown_at_bottom_is_noop(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"\x1b[B", b"\x1b[B", b"\x1b", b"\x1b"],
        branches=["alpha"],
    )
    assert cfg is None


def test_branch_config_panel_dropdown_scroll_up_and_down(tmp_path: Path) -> None:
    branches = [f"branch-{i}" for i in range(8)]
    with patch("shutil.get_terminal_size", return_value=__import__("os").terminal_size((80, 20))):
        cfg = _panel(
            tmp_path,
            [b"\x1b[D", b"\r"] + [b"\x1b[B"] * 9 + [b"\x1b[A"] * 8 + [b"\x1b", b"\x1b"],
            branches=branches,
        )
    assert cfg is None


def test_branch_config_panel_name_empty_error_while_editing(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\r", b"\x1b", b"\x1b"],
        workspace_name="",
    )
    assert cfg is None


def test_branch_config_panel_name_exists_error_while_editing(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"\r", b"\x1b", b"\x1b"],
        workspace_name="taken-branch",
        branches=["taken-branch"],
    )
    assert cfg is None


def test_branch_config_panel_types_char_in_name_field(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\r", b"x", b"\r", b"\x1b[B", b"\r"],
        workspace_name="feat",
    )
    assert cfg == RepoConfig(name="svc", mode="new", branch="featx", parent="main")


def test_branch_config_panel_existing_typed_exact_match_success(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"a", b"l", b"p", b"h", b"a", b"\r", b"\r"],
        branches=["alpha", "beta"],
    )
    assert cfg == RepoConfig(name="svc", mode="existing", branch="alpha", parent=None)


def test_branch_config_panel_backspace_while_not_editing_is_noop(tmp_path: Path) -> None:
    cfg = _panel(tmp_path, [b"\x7f", b"\x1b"])
    assert cfg is None


def test_branch_config_panel_prefetch_thread_still_running(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    fake_fd = FakeTty()
    started = _threading.Event()
    release = _threading.Event()

    def _slow() -> None:
        started.set()
        release.wait(timeout=2)

    thread = _threading.Thread(target=_slow, daemon=True)
    thread.start()
    started.wait(timeout=2)
    try:
        with patch.object(cr, "_read_key", side_effect=[b"\x1b"]):
            cfg = cr._branch_config_panel(
                repo_name="svc",
                workspace_name="feat",
                repo_path=repo_path,
                tty_fd=fake_fd,
                old_attrs=None,
                pre_fetch_thread=thread,
                pre_fetch_cache={"svc": []},
            )
    finally:
        release.set()
        thread.join(timeout=2)
    assert cfg is None
    _time.sleep(0)  # ensure the thread finished before test teardown


def test_branch_config_panel_up_arrow_picker_at_initial_idx_is_noop(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"\x1b[A", b"\x1b", b"\x1b"],
        branches=["alpha"],
    )
    assert cfg is None


def test_confirm_panel_ctrl_c_exits(tmp_path: Path) -> None:
    fake_fd = FakeTty()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with (
        patch.object(cr, "_read_key", side_effect=[b"\x03"]),
        patch("termios.tcsetattr") as mock_set,
        pytest.raises(SystemExit) as exc_info,
    ):
        _confirm_panel([cfg], fake_fd, None)
    assert exc_info.value.code == 130
    mock_set.assert_called_once()


def test_confirm_panel_unmapped_key_then_confirm() -> None:
    fake_fd = FakeTty()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="main")
    with patch.object(cr, "_read_key", side_effect=[b"z", b"\r"]):
        assert _confirm_panel([cfg], fake_fd, None) is True


def test_branch_config_panel_existing_backspace_at_start_is_noop(tmp_path: Path) -> None:
    cfg = _panel(
        tmp_path,
        [b"\x1b[D", b"\r", b"\x7f", b"\x1b", b"\x1b"],
        branches=["main"],
    )
    assert cfg is None


def test_tty_write_encodes() -> None:
    fake_fd = FakeTty()
    cr._tty_write(fake_fd, "hello")
    assert fake_fd.written == [b"hello"]


def test_fetch_branches_skips_blank_lines(tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="main\n\nfeature\n", stderr=""
    )
    with patch("subprocess.run", return_value=completed):
        branches = fetch_branches(tmp_path, skip_fetch=True)
    assert branches == ["feature", "main"]


def test_parse_worktrees_entry_without_branch_is_dropped() -> None:
    # A bare worktree entry (e.g. detached HEAD) has no "branch " line before the
    # blank separator, so it is not included in the result; an unrecognized line
    # in between is ignored, and a trailing entry with no separator is still
    # captured at the end.
    porcelain = "worktree /repo\nHEAD abc123\ndetached\n\nworktree /repo2\nbranch refs/heads/x\n"
    result = _parse_worktrees(porcelain)
    assert result == [(Path("/repo2"), "refs/heads/x")]


def _panel(
    tmp_path: Path,
    keys: list[bytes],
    *,
    workspace_name: str = "myfeature",
    branches: list[str] | None = None,
) -> RepoConfig | None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir(exist_ok=True)
    fake_fd = FakeTty()
    with patch.object(cr, "_read_key", side_effect=keys):
        return cr._branch_config_panel(
            repo_name="svc",
            workspace_name=workspace_name,
            repo_path=repo_path,
            tty_fd=fake_fd,
            old_attrs=None,
            pre_fetch_cache={"svc": branches or []},
        )


def test_pre_validate_existing_branch_multiple_worktrees_no_match(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="existing", branch="feature")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "list"):
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=0,
                stdout="worktree /other\nbranch refs/heads/unrelated\n\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with patch.object(cr, "run_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert errors == []


def test_pre_validate_existing_branch_not_found_anywhere(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="existing", branch="feature")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "list"):
            return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="")

    with patch.object(cr, "run_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert errors == []
    assert cfg.is_remote_only is False


def test_pre_validate_new_parent_found_on_remote_only(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    cfg = RepoConfig(name="svc", mode="new", branch="feature", parent="develop")

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if "refs/remotes/origin/develop" in args:
            return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="")

    with patch.object(cr, "run_git", side_effect=fake_git):
        errors = pre_validate([cfg], {"svc": repo_path})
    assert errors == []


def test_pre_validate_new_no_parent_and_existing_no_conflict(tmp_path: Path) -> None:
    repo_path = tmp_path / "svc"
    repo_path.mkdir()
    configs = [
        RepoConfig(name="a", mode="existing", branch="feature"),
        RepoConfig(name="b", mode="new", branch="feature", parent="main"),
        RepoConfig(name="c", mode="new", branch="feature", parent=None),
    ]
    repo_paths = {"a": repo_path, "b": repo_path, "c": repo_path}

    def fake_git(rp: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "list"):
            return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with patch.object(cr, "run_git", side_effect=fake_git):
        errors = pre_validate(configs, repo_paths)
    assert errors == []
