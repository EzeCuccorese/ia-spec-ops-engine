"""
Unit tests for workspace_engine.services.tui_utils — terminal helpers used by the
interactive repository selector and configurator.

`_read_key` and `read_key` touch `termios`/`select`/`tty`; they are deterministically
tested by patching those modules rather than driving a real terminal.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

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


def test_write_tty_with_file_like_str_input() -> None:
    fake = MagicMock()
    tu.write_tty(fake, "hello")
    fake.write.assert_called_once_with(b"hello")
    fake.flush.assert_called_once()


def test_write_tty_with_file_like_bytes_input() -> None:
    fake = MagicMock()
    tu.write_tty(fake, b"raw-bytes")
    fake.write.assert_called_once_with(b"raw-bytes")
    fake.flush.assert_called_once()


def test_write_tty_with_raw_fd() -> None:
    with patch("os.write") as mock_write:
        tu.write_tty(5, "hi")
    mock_write.assert_called_once_with(5, b"hi")


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


def test__read_key_accumulates_escape_sequence() -> None:
    fake_fd = MagicMock()
    fake_fd.read.side_effect = [b"\x1b", b"[", b"A"]
    with patch(
        "workspace_engine.services.tui_utils._select.select",
        side_effect=[([fake_fd], [], []), ([fake_fd], [], [])],
    ):
        result = tu._read_key(fake_fd)
    assert result == b"\x1b[A"


def test__read_key_escape_alone_times_out() -> None:
    fake_fd = MagicMock()
    fake_fd.read.side_effect = [b"\x1b"]
    with patch("workspace_engine.services.tui_utils._select.select", return_value=([], [], [])):
        result = tu._read_key(fake_fd)
    assert result == b"\x1b"


def test__read_key_stops_on_tilde_terminator() -> None:
    fake_fd = MagicMock()
    fake_fd.read.side_effect = [b"\x1b", b"1", b"~"]
    with patch(
        "workspace_engine.services.tui_utils._select.select",
        side_effect=[([fake_fd], [], []), ([fake_fd], [], [])],
    ):
        result = tu._read_key(fake_fd)
    assert result == b"\x1b1~"


def test_resolve_cursor_no_sentinel_returns_default_hide_sequence() -> None:
    frame, cur_seq = tu._resolve_cursor("no sentinel here")
    assert frame == "no sentinel here"
    assert cur_seq == "\033[?25l"


def test_resolve_cursor_finds_position_without_home_sequence() -> None:
    output = "line1\r\nline2\x00rest"
    frame, cur_seq = tu._resolve_cursor(output)
    assert frame == "line1\r\nline2rest"
    assert cur_seq == "\033[2;6H\033[?25h"


def test_resolve_cursor_finds_position_after_home_sequence() -> None:
    output = "junk\033[Hline1\r\nab\x00rest"
    frame, cur_seq = tu._resolve_cursor(output)
    assert frame == "junk\033[Hline1\r\nabrest"
    assert cur_seq == "\033[2;3H\033[?25h"


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
