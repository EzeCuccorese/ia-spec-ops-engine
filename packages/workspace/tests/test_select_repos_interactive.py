"""
Interactive-loop tests for workspace_engine.services.select_repos.select_repos,
using a fake tty descriptor and mocked termios/tty calls so no real terminal is required.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.services import select_repos as sr


class FakeTty:
    """Minimal file-like stand-in for the raw /dev/tty descriptor."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def fileno(self) -> int:
        return 99

    def close(self) -> None:
        self.closed = True


def _make_repos(tmp_path: Path, names: list[str]) -> Path:
    repos_root = tmp_path / "repos"
    for name in names:
        d = repos_root / name
        d.mkdir(parents=True)
        (d / ".git").mkdir()
    return repos_root


def _run_with_keys(tmp_path: Path, repos: list[str], keys: list[bytes], **kwargs):
    repos_root = _make_repos(tmp_path, repos)
    fake_fd = FakeTty()
    with (
        patch.object(sr, "_open_tty", return_value=fake_fd),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(sr, "_read_key", side_effect=keys),
    ):
        return sr.select_repos(
            toolkit_dir=tmp_path,
            repos_root=repos_root,
            **kwargs,
        )


def test_select_repos_esc_returns_none(tmp_path: Path) -> None:
    result = _run_with_keys(tmp_path, ["auth-service"], [b"\x1b"])
    assert result is None


def test_select_repos_ctrl_c_returns_none(tmp_path: Path) -> None:
    result = _run_with_keys(tmp_path, ["auth-service"], [b"\x03"])
    assert result is None


def test_select_repos_no_open_tty_fallback(tmp_path: Path) -> None:
    repos_root = _make_repos(tmp_path, ["auth-service"])
    with patch.object(sr, "_open_tty", side_effect=OSError("no tty")):
        result = sr.select_repos(toolkit_dir=tmp_path, repos_root=repos_root)
    assert result == []


def test_select_repos_select_one_and_confirm(tmp_path: Path) -> None:
    # space toggles first item, enter confirms
    result = _run_with_keys(tmp_path, ["auth-service", "payment-service"], [b" ", b"\r"])
    assert result == ["auth-service"]


def test_select_repos_enter_without_selection_then_select(tmp_path: Path) -> None:
    # Enter with nothing selected shows an error but keeps looping; then select and confirm.
    result = _run_with_keys(tmp_path, ["auth-service"], [b"\r", b" ", b"\r"])
    assert result == ["auth-service"]


def test_select_repos_navigate_down_and_select(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service", "payment-service"],
        [b"\x1b[B", b" ", b"\r"],
    )
    assert result == ["payment-service"]


def test_select_repos_navigate_up_stays_at_top(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service", "payment-service"],
        [b"\x1b[A", b" ", b"\r"],
    )
    assert result == ["auth-service"]


def test_select_repos_toggle_off_selection(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b" ", b" ", b"\r", b"\x1b"],
    )
    # Toggled on then off -> nothing selected -> error shown -> loop continues, then ESC exits.
    assert result is None


def test_select_repos_filter_types_and_backspace(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service", "payment-service"],
        [b"a", b"u", b"\x7f", b" ", b"\r"],
    )
    assert result == ["auth-service"]


def test_select_repos_filter_arrow_and_home_end(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b"a", b"\x1b[D", b"\x1b[C", b"\x1b[H", b"\x1b[F", b"\x1b[3~", b" ", b"\r"],
    )
    assert result == ["auth-service"]


def test_select_repos_locked_item_rejected(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b" ", b"\x1b"],
        locked=["auth-service"],
    )
    assert result is None


def test_select_repos_preselected(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service", "payment-service"],
        [b"\r"],
        preselected=["auth-service"],
    )
    assert result == ["auth-service"]


def test_select_repos_toolkit_selected(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b" ", b"\r"],
        show_toolkit=True,
    )
    assert result == [sr.TOOLKIT_NAME]


def test_load_repos_nonexistent_root(tmp_path: Path) -> None:
    assert sr.load_repos(tmp_path / "does-not-exist") == []


def test_load_repos_skips_non_git_dirs(tmp_path: Path) -> None:
    repos_root = tmp_path / "repos"
    repos_root.mkdir()
    (repos_root / "has-git").mkdir()
    (repos_root / "has-git" / ".git").mkdir()
    (repos_root / "no-git").mkdir()
    (repos_root / "a-file.txt").write_text("x", encoding="utf-8")
    result = sr.load_repos(repos_root)
    assert result == ["has-git"]


def test_open_tty_opens_the_controlling_terminal_unbuffered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[tuple, dict]] = []

    def fake_open(*args, **kwargs):
        opened.append((args, kwargs))
        return "tty"

    monkeypatch.setattr("builtins.open", fake_open)
    assert sr._open_tty() == "tty"
    assert opened == [(("/dev/tty", "rb+"), {"buffering": 0})]


def test_select_repos_preselected_item_not_available_is_skipped(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b"\r", b" ", b"\r"],
        preselected=["nonexistent-repo"],
    )
    assert result == ["auth-service"]


def test_select_repos_locked_item_not_available_is_ignored(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b" ", b"\r"],
        locked=["nonexistent-repo"],
    )
    assert result == ["auth-service"]


def test_select_repos_filter_reduces_results_resets_cursor(tmp_path: Path) -> None:
    # Move cursor to the second item, then type a filter that only matches the first,
    # forcing the out-of-range cursor back to 0.
    result = _run_with_keys(
        tmp_path,
        ["auth-service", "payment-service"],
        [b"\x1b[B", b"a", b"u", b"t", b"h", b" ", b"\r"],
    )
    assert result == ["auth-service"]


def test_select_repos_no_match_shows_message_then_clears_filter(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b"z", b"z", b"z", b"\x7f", b"\x7f", b"\x7f", b" ", b"\r"],
    )
    assert result == ["auth-service"]


def test_select_repos_add_new_label_selected_adds_custom_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos_root = _make_repos(tmp_path, [sr.ADD_NEW_LABEL])
    fake_fd1 = FakeTty()
    fake_fd2 = FakeTty()
    monkeypatch.setattr("sys.stdin", io.StringIO("brand-new-repo\n"))
    with (
        patch.object(sr, "_open_tty", side_effect=[fake_fd1, fake_fd2]),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(sr, "_read_key", side_effect=[b" ", b"\r"]),
    ):
        result = sr.select_repos(toolkit_dir=tmp_path, repos_root=repos_root)
    assert result == ["brand-new-repo"]


def test_select_repos_add_new_label_empty_name_not_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos_root = _make_repos(tmp_path, [sr.ADD_NEW_LABEL])
    fake_fd1 = FakeTty()
    fake_fd2 = FakeTty()
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    with (
        patch.object(sr, "_open_tty", side_effect=[fake_fd1, fake_fd2]),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(sr, "_read_key", side_effect=[b" ", b"\r", b"\x1b"]),
    ):
        result = sr.select_repos(toolkit_dir=tmp_path, repos_root=repos_root)
    # Nothing got added, confirming with Enter shows an error and loops; ESC exits.
    assert result is None


def test_select_repos_toggle_off_custom_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos_root = _make_repos(tmp_path, [sr.ADD_NEW_LABEL, "auth-service"])
    fake_fd1 = FakeTty()
    fake_fd2 = FakeTty()
    monkeypatch.setattr("sys.stdin", io.StringIO("auth-service\n"))
    with (
        patch.object(sr, "_open_tty", side_effect=[fake_fd1, fake_fd2]),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(sr, "_read_key", side_effect=[b" ", b"\x1b[B", b" ", b"\x1b"]),
    ):
        result = sr.select_repos(toolkit_dir=tmp_path, repos_root=repos_root)
    assert result is None


def test_select_repos_scroll_down_and_up(tmp_path: Path) -> None:
    import os as os_mod

    repos = [f"repo-{i}" for i in range(6)]
    with patch("shutil.get_terminal_size", return_value=os_mod.terminal_size((80, 17))):
        result = _run_with_keys(
            tmp_path,
            repos,
            [
                b"\x1b[B",
                b"\x1b[B",
                b"\x1b[B",
                b"\x1b[B",
                b"\x1b[B",
                b"\x1b[A",
                b"\x1b[A",
                b"\x1b[A",
                b"\x1b[A",
                b" ",
                b"\r",
            ],
        )
    assert result == ["repo-1"]


def test_select_repos_toolkit_up_arrow_rc_negative_resets_scroll(tmp_path: Path) -> None:
    result = _run_with_keys(
        tmp_path,
        ["auth-service", "payment-service"],
        [b"\x1b[B", b"\x1b[A", b" ", b"\r"],
        show_toolkit=True,
    )
    assert result == [sr.TOOLKIT_NAME]


def test_select_repos_cursor_reset_when_filter_narrows_via_delete(tmp_path: Path) -> None:
    # "abcac-x" contains both "abc" and "ac" as substrings; "abcxy" contains "abc"
    # but not "ac". Typing "abc" matches both (cursor reset to 0 by typing), moving
    # down selects the second ("abcxy"), then deleting the middle 'b' narrows the
    # filter to "ac", which drops "abcxy" from the results while the stale cursor
    # (1) is now out of range and must reset to 0.
    result = _run_with_keys(
        tmp_path,
        ["abcac-x", "abcxy"],
        [
            b"a",
            b"b",
            b"c",
            b"\x1b[B",
            b"\x1b[D",
            b"\x1b[D",
            b"\x1b[3~",
            b" ",
            b"\r",
        ],
    )
    assert result == ["abcac-x"]


def test_select_repos_down_arrow_at_bottom_is_noop(tmp_path: Path) -> None:
    # Cursor is already on the last (only) item; another Down arrow does nothing.
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b"\x1b[B", b" ", b"\r"],
    )
    assert result == ["auth-service"]


def test_select_repos_toolkit_toggle_on_then_off(tmp_path: Path) -> None:
    # Selecting the toolkit then deselecting it exercises the "toggle off" path,
    # which skips clearing selections and resetting the cursor.
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b" ", b" ", b"\x1b[B", b" ", b"\r"],
        show_toolkit=True,
    )
    assert result == ["auth-service"]


def test_select_repos_filter_arrows_are_noop_when_toolkit_selected(tmp_path: Path) -> None:
    # While the toolkit row is selected, filter navigation keys (left/right, home,
    # end) are no-ops because editing is disabled.
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [
            b" ",  # select toolkit
            b"\x1b[D",
            b"\x1b[C",
            b"\x1b[H",
            b"\x1b[1~",
            b"\x1b[F",
            b"\x1b[4~",
            b"\x1b[3~",
            b"\x7f",
            b"\r",
        ],
        show_toolkit=True,
    )
    assert result == [sr.TOOLKIT_NAME]


def test_select_repos_space_with_no_matches_is_noop(tmp_path: Path) -> None:
    # No repositories at all: filtered is empty, so the space key's item_idx
    # bounds check fails and nothing happens.
    repos_root = tmp_path / "repos"
    repos_root.mkdir()
    fake_fd = FakeTty()
    with (
        patch.object(sr, "_open_tty", return_value=fake_fd),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(sr, "_read_key", side_effect=[b" ", b"\x1b"]),
    ):
        result = sr.select_repos(toolkit_dir=tmp_path, repos_root=repos_root)
    assert result is None


def test_select_repos_unmapped_control_key_is_ignored(tmp_path: Path) -> None:
    # A control byte that is not printable and matches none of the mapped keys
    # falls through the final else branch without changing any state.
    result = _run_with_keys(
        tmp_path,
        ["auth-service"],
        [b"\x01", b" ", b"\r"],
    )
    assert result == ["auth-service"]


def test_select_repos_no_repos_root(tmp_path: Path) -> None:
    fake_fd = FakeTty()
    with (
        patch.object(sr, "_open_tty", return_value=fake_fd),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr"),
        patch("tty.setraw"),
        patch.object(sr, "_read_key", side_effect=[b"\x1b"]),
    ):
        result = sr.select_repos(toolkit_dir=tmp_path, repos_root=None)
    assert result is None
