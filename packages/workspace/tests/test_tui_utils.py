"""
Unit tests for workspace_engine.services.tui_utils — terminal helpers used by the
interactive repository selector and configurator.

`_read_key` and `read_key` touch `termios`/`select`/`tty`; they are deterministically
tested by patching those modules rather than driving a real terminal.
"""

from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.services import tui_utils as tu


def test_strip_ansi_removes_escape_sequences() -> None:
    assert tu.strip_ansi("\033[1;32mHello\033[0m") == "Hello"


def test_strip_ansi_removes_single_char_escape() -> None:
    # \x1bM is a non-CSI escape (not followed by '['), matched by the second alternative.
    assert tu.strip_ansi("a\x1bMb") == "ab"


def test_pad_colored_pads_to_width() -> None:
    result = tu.pad_colored("Hello", 10, "\033[32mHello\033[0m")
    assert result == "\033[32mHello\033[0m" + " " * 5


def test_pad_colored_no_padding_when_over_width() -> None:
    result = tu.pad_colored("Hello World", 3, "Hello World")
    assert result == "Hello World"


def test_draw_separator_bold() -> None:
    sep = tu.draw_separator(10, char="-", bold=True)
    assert sep == f"\033[1m{'-' * 10}\033[0m"


def test_draw_separator_not_bold() -> None:
    sep = tu.draw_separator(10, char="-", bold=False)
    assert sep == "-" * 10


def test_draw_separator_minimum_width_one() -> None:
    sep = tu.draw_separator(0, char="=")
    assert tu.strip_ansi(sep) == "="


def test_open_tty_success() -> None:
    fake_file = MagicMock()
    with patch("builtins.open", return_value=fake_file) as mock_open:
        result = tu.open_tty()
    mock_open.assert_called_once_with("/dev/tty", "rb+", buffering=0)
    assert result is fake_file


def test_open_tty_falls_back_to_stdin_on_oserror() -> None:
    with patch("builtins.open", side_effect=OSError("no tty")):
        result = tu.open_tty()
    import sys

    assert result is sys.stdin


@pytest.mark.parametrize(
    ("data", "expected"), [("hello", b"hello"), (b"raw-bytes", b"raw-bytes")], ids=["str", "bytes"]
)
def test_write_tty_with_file_like(data: str | bytes, expected: bytes) -> None:
    sink = io.BytesIO()
    tu.write_tty(sink, data)
    assert sink.getvalue() == expected


def test_write_tty_with_raw_fd() -> None:
    read_fd, write_fd = os.pipe()
    try:
        tu.write_tty(write_fd, "hi")
        assert os.read(read_fd, 16) == b"hi"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_read_key_returns_bytes_when_ready() -> None:
    fake_fd = MagicMock()
    fake_fd.fileno.return_value = 7
    with (
        patch("termios.tcgetattr", return_value=["old"]) as mock_get,
        patch("termios.tcsetattr") as mock_set,
        patch.object(tu, "tty") as mock_tty,
        patch("workspace_engine.services.tui_utils._select.select", return_value=([7], [], [])),
        patch("os.read", return_value=b"a") as mock_read,
    ):
        result = tu.read_key(fake_fd, timeout=0.01)
    assert result == b"a"
    mock_get.assert_called_once_with(7)
    mock_tty.setraw.assert_called_once_with(7)
    mock_read.assert_called_once_with(7, 8)
    mock_set.assert_called_once_with(7, tu.termios.TCSADRAIN, ["old"])


def test_read_key_returns_none_on_timeout() -> None:
    fake_fd = MagicMock()
    fake_fd.fileno.return_value = 7
    with (
        patch("termios.tcgetattr", return_value=["old"]),
        patch("termios.tcsetattr"),
        patch.object(tu, "tty") as mock_tty,
        patch("workspace_engine.services.tui_utils._select.select", return_value=([], [], [])),
    ):
        result = tu.read_key(fake_fd, timeout=0.01)
    assert result is None
    mock_tty.setraw.assert_called_once()


def test_read_key_without_tty_module_available() -> None:
    fake_fd = MagicMock()
    fake_fd.fileno.return_value = 7
    with (
        patch("termios.tcgetattr", return_value=["old"]),
        patch("termios.tcsetattr"),
        patch.object(tu, "tty", None),
        patch("workspace_engine.services.tui_utils._select.select", return_value=([], [], [])),
    ):
        result = tu.read_key(fake_fd, timeout=0.01)
    assert result is None


def test_read_key_accepts_raw_fd_int() -> None:
    with (
        patch("termios.tcgetattr", return_value=["old"]),
        patch("termios.tcsetattr"),
        patch.object(tu, "tty") as mock_tty,
        patch("workspace_engine.services.tui_utils._select.select", return_value=([], [], [])),
    ):
        result = tu.read_key(9, timeout=0.01)
    assert result is None
    mock_tty.setraw.assert_called_once_with(9)


def test__read_key_returns_simple_byte() -> None:
    fake_fd = io.BytesIO(b"a")
    result = tu._read_key(fake_fd)
    assert result == b"a"


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [([b"\x1b", b"[", b"A"], b"\x1b[A"), ([b"\x1b", b"1", b"~"], b"\x1b1~")],
    ids=["csi-letter", "tilde-terminator"],
)
def test__read_key_accumulates_escape_sequence(chunks: list[bytes], expected: bytes) -> None:
    fake_fd = MagicMock()
    fake_fd.read.side_effect = chunks
    with patch(
        "workspace_engine.services.tui_utils._select.select",
        side_effect=[([fake_fd], [], []), ([fake_fd], [], [])],
    ):
        result = tu._read_key(fake_fd)
    assert result == expected


def test__read_key_escape_alone_times_out() -> None:
    fake_fd = MagicMock()
    fake_fd.read.side_effect = [b"\x1b"]
    with patch("workspace_engine.services.tui_utils._select.select", return_value=([], [], [])):
        result = tu._read_key(fake_fd)
    assert result == b"\x1b"


def test_resolve_cursor_no_sentinel_returns_default_hide_sequence() -> None:
    frame, cur_seq = tu._resolve_cursor("no sentinel here")
    assert frame == "no sentinel here"
    assert cur_seq == "\033[?25l"


@pytest.mark.parametrize(
    ("output", "frame", "cur_seq"),
    [
        ("line1\r\nline2\x00rest", "line1\r\nline2rest", "\033[2;6H\033[?25h"),
        ("junk\033[Hline1\r\nab\x00rest", "junk\033[Hline1\r\nabrest", "\033[2;3H\033[?25h"),
    ],
    ids=["without-home-sequence", "after-home-sequence"],
)
def test_resolve_cursor_finds_position(output: str, frame: str, cur_seq: str) -> None:
    assert tu._resolve_cursor(output) == (frame, cur_seq)


def test_tty_import_error_fallback_sets_tty_none() -> None:
    """When the `tty` module is unavailable, the module falls back to `tty = None`."""
    import importlib
    import sys

    with patch.dict(sys.modules, {"tty": None}):
        importlib.reload(tu)
    try:
        assert tu.tty is None
    finally:
        importlib.reload(tu)
