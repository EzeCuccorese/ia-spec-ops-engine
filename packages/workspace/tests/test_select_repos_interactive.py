"""
Interactive-loop tests for workspace_engine.services.select_repos.select_repos,
using a fake tty descriptor and mocked termios/tty calls so no real terminal is required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
