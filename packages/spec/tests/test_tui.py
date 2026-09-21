"""Tests for the arrow-key TUI helpers in spec.core.tui."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from spec.core import tui


class FakeStdin:
    """Minimal stand-in for sys.stdin driven by a scripted list of reads."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)

    def fileno(self) -> int:
        return 0

    def read(self, _n: int) -> str:
        return self._chunks.pop(0)


def _patch_raw_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the raw-terminal syscalls so get_key() runs outside a real TTY."""
    import termios
    import tty

    monkeypatch.setattr(termios, "tcgetattr", lambda fd: "old-settings")
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, settings: None)
    monkeypatch.setattr(tty, "setraw", lambda fd: None)


def test_get_key_regular_character(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin(["x"]))
    assert tui.get_key() == "x"


def test_get_key_enter_via_carriage_return(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin(["\r"]))
    assert tui.get_key() == "ENTER"


def test_get_key_enter_via_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin(["\n"]))
    assert tui.get_key() == "ENTER"


def test_get_key_space(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin([" "]))
    assert tui.get_key() == "SPACE"


def test_get_key_ctrl_c_raises_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin(["\x03"]))
    with pytest.raises(KeyboardInterrupt):
        tui.get_key()


@pytest.mark.parametrize(
    ("arrow_char", "expected"),
    [("A", "UP"), ("B", "DOWN"), ("C", "RIGHT"), ("D", "LEFT")],
)
def test_get_key_arrow_sequences(
    monkeypatch: pytest.MonkeyPatch, arrow_char: str, expected: str
) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin(["\x1b", "[", arrow_char]))
    assert tui.get_key() == expected


def test_get_key_lone_escape_returns_esc(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin(["\x1b", "x"]))
    assert tui.get_key() == "ESC"


def test_get_key_unknown_bracket_sequence_returns_esc(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_raw_mode(monkeypatch)
    monkeypatch.setattr(tui.sys, "stdin", FakeStdin(["\x1b", "[", "Z"]))
    assert tui.get_key() == "ESC"


def test_select_one_returns_default_when_not_a_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tui.sys.stdin, "isatty", lambda: False)
    result = tui.select_one("Pick one", ["a", "b", "c"], default_index=2)
    assert result == 2
    assert capsys.readouterr().out == ""


def test_select_multiple_returns_defaults_when_not_a_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tui.sys.stdin, "isatty", lambda: False)
    options = [("a", "Option A"), ("b", "Option B")]
    assert tui.select_multiple("Pick some", options) == ["a", "b"]
    assert tui.select_multiple("Pick some", options, default_checked=["b"]) == ["b"]
    assert capsys.readouterr().out == ""


def test_select_one_tty_navigation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tui.sys.stdin, "isatty", lambda: True)
    # Wrap around upward from index 0, move down twice, hit an unrecognized key
    # (no-op redraw), then confirm.
    with patch.object(tui, "get_key", side_effect=["UP", "DOWN", "DOWN", "x", "ENTER"]):
        result = tui.select_one("Pick one", ["a", "b", "c"], default_index=0)
    assert result == 1
    out = capsys.readouterr().out
    assert "Pick one" in out
    assert "Selected:" in out
    assert out.count("b") >= 1


def test_select_multiple_tty_toggle_and_select_all(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tui.sys.stdin, "isatty", lambda: True)
    options = [("a", "Option A"), ("b", "Option B")]
    keys = [
        "DOWN",  # move cursor to b
        "UP",  # move cursor back to a
        "SPACE",  # untoggle b? no: cursor is on a, untoggle a
        "a",  # since not all checked, "a" selects all again
        "A",  # since all checked, "A" clears all
        "z",  # unrecognized key, no state change, just redraw
        "ENTER",
    ]
    with patch.object(tui, "get_key", side_effect=keys):
        result = tui.select_multiple("Pick some", options, default_checked=["a", "b"])
    assert result == []
    out = capsys.readouterr().out
    assert "Pick some" in out
    assert "Selected" in out
    assert "items." in out


def test_select_multiple_tty_default_checked_none_checks_all(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tui.sys.stdin, "isatty", lambda: True)
    options = [("a", "Option A"), ("b", "Option B")]
    with patch.object(tui, "get_key", side_effect=["SPACE", "ENTER"]):
        result = tui.select_multiple("Pick some", options)
    assert result == ["b"]


def test_select_multiple_tty_space_adds_when_unchecked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tui.sys.stdin, "isatty", lambda: True)
    options = [("a", "Option A"), ("b", "Option B")]
    with patch.object(tui, "get_key", side_effect=["SPACE", "ENTER"]):
        result = tui.select_multiple("Pick some", options, default_checked=["b"])
    assert result == ["a", "b"]


def test_spec_main_module_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that running spec as a module invokes the CLI."""
    import runpy
    import sys

    from spec import cli

    monkeypatch.setattr(sys, "argv", ["spec"])

    with patch.object(cli, "main") as mock_main:
        runpy.run_module("spec", run_name="__main__", alter_sys=True)
    mock_main.assert_called_once()
