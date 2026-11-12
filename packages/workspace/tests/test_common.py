"""
Tests for the shared workspace_engine.common utilities (colors and subprocess).
"""

from workspace_engine.common import Color, colorize, run_command_safe


def test_colorize() -> None:
    res = colorize("hello", Color.GREEN)
    assert Color.GREEN in res
    assert Color.RESET in res
    assert "hello" in res


def test_run_command_safe_echo() -> None:
    code, stdout, _stderr = run_command_safe(["echo", "workspace"])
    assert code == 0
    assert "workspace" in stdout


def test_run_command_safe_timeout() -> None:
    code, _stdout, stderr = run_command_safe(["sleep", "2"], timeout=1)
    assert code == 124
    assert "TimeoutExpired" in stderr
