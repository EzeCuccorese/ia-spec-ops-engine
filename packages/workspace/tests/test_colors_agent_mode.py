"""Tests for workspace_engine.common.colors — agent mode output functions."""

from __future__ import annotations

import sys

import pytest
from workspace_engine.common.colors import (
    emit_rows,
    is_agent_mode,
    log_error,
    log_info,
    log_success,
    log_warning,
    truncate,
)


class TestIsAgentMode:
    """Test is_agent_mode() behavior (same 4 cases as ai_governance)."""

    @pytest.mark.parametrize(
        ("env", "tty", "expected"),
        [
            ("1", True, True),  # WORKSPACE_AGENT=1 forces ON even on a TTY
            ("0", False, False),  # WORKSPACE_AGENT=0 forces OFF even off a TTY
            (None, True, False),  # unset + TTY
            (None, False, False),  # plain pipe keeps full human output
        ],
    )
    def test_agent_mode_env_and_tty(
        self, monkeypatch: pytest.MonkeyPatch, env: str | None, tty: bool, expected: bool
    ) -> None:
        if env is None:
            monkeypatch.delenv("WORKSPACE_AGENT", raising=False)
        else:
            monkeypatch.setenv("WORKSPACE_AGENT", env)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: tty)
        assert is_agent_mode() is expected

    @pytest.mark.parametrize(
        "marker", ["CLAUDE_CODE_CHILD_SESSION", "CLAUDECODE", "CODEX_SANDBOX", "ANTIGRAVITY_AGENT"]
    )
    def test_agent_mode_on_when_agent_marker_set(
        self, monkeypatch: pytest.MonkeyPatch, marker: str
    ) -> None:
        monkeypatch.delenv("WORKSPACE_AGENT", raising=False)
        monkeypatch.setenv(marker, "1")
        assert is_agent_mode() is True


class TestTruncate:
    """Test truncate() line and character limits (same as ai_governance)."""

    def test_truncate_no_op_under_limits(self) -> None:
        """Text under both limits is returned unchanged."""
        text = "line1\nline2\nline3"
        result = truncate(text, max_lines=20, max_chars=1500)
        assert result == text

    def test_truncate_line_cut_exact_max_lines(self) -> None:
        """Exceeding max_lines cuts to exactly max_lines with 'more:' at end."""
        lines = [f"line{i}" for i in range(30)]
        text = "\n".join(lines)
        result = truncate(text, max_lines=5, max_chars=1500)
        result_lines = result.split("\n")
        assert len(result_lines) == 5
        assert result_lines[-1] == "more:"

    def test_truncate_char_cut_respects_budget(self) -> None:
        """Exceeding max_chars cuts at line boundary and adds 'more:'."""
        lines = ["x" * 200 for _ in range(20)]
        text = "\n".join(lines)
        result = truncate(text, max_lines=100, max_chars=500)
        assert len(result) <= 500
        assert result.split("\n")[-1].startswith("more:")

    def test_truncate_char_cut_with_empty_candidate_lines(self) -> None:
        """A negative max_chars forces needs_char_cut on an already-empty candidate list."""
        text = "line1\nline2\nline3"
        result = truncate(text, max_lines=1, max_chars=-1)
        assert result == "more:"


class TestEmitRows:
    """Test emit_rows() in agent mode."""

    def test_emit_rows_agent_mode_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode emits title, headers, and rows joined with ' | '."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        rows = [("a", "b", "c"), ("d", "e", "f")]
        emit_rows(rows, headers=("H1", "H2", "H3"), title="Table")
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert lines[0] == "Table"
        assert lines[1] == "H1 | H2 | H3"
        assert lines[2] == "a | b | c"
        assert lines[3] == "d | e | f"

    def test_emit_rows_agent_mode_full_true_no_truncate(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with full=True never truncates."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        rows = [(f"r{i}", f"d{i}") for i in range(50)]
        emit_rows(rows, headers=("ID", "Data"), full=True)
        out = capsys.readouterr().out
        assert "more:" not in out

    def test_emit_rows_agent_mode_no_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode output contains no ANSI escape sequences."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        rows = [("cell1", "cell2")]
        emit_rows(rows, headers=("H1", "H2"), title="Test")
        out = capsys.readouterr().out
        assert "\x1b" not in out

    def test_emit_rows_agent_mode_without_headers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with no headers skips the header line."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        rows = [("a", "b")]
        emit_rows(rows)
        out = capsys.readouterr().out.strip()
        assert out == "a | b"

    def test_emit_rows_tty_mode_renders_table(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Non-agent mode renders a Rich table instead of plain lines."""
        monkeypatch.setenv("WORKSPACE_AGENT", "0")
        rows = [("x", "y")]
        emit_rows(rows, headers=("Col1", "Col2"), title="My Table")
        out = capsys.readouterr().out
        assert "My Table" in out
        assert "Col1" in out


class TestLogFunctions:
    """Test log_info, log_success, log_warning, log_error in agent mode."""

    def test_log_info_agent_mode_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode log_info() outputs 'INFO: message' to stdout."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        log_info("Test info message")
        out = capsys.readouterr()
        assert out.out == "INFO: Test info message\n"
        assert out.err == ""

    def test_log_info_tty_mode_has_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode log_info() contains ANSI codes."""
        monkeypatch.setenv("WORKSPACE_AGENT", "0")
        log_info("Test info")
        out = capsys.readouterr().out
        assert "\x1b" in out

    def test_log_success_agent_mode_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode log_success() outputs 'OK: message' to stdout."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        log_success("Operation worked")
        out = capsys.readouterr()
        assert out.out == "OK: Operation worked\n"
        assert out.err == ""

    def test_log_success_tty_mode_has_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode log_success() contains ANSI codes."""
        monkeypatch.setenv("WORKSPACE_AGENT", "0")
        log_success("Operation worked")
        out = capsys.readouterr().out
        assert "\x1b" in out

    def test_log_warning_agent_mode_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode log_warning() outputs 'WARN: message' to stdout."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        log_warning("Be careful")
        out = capsys.readouterr()
        assert out.out == "WARN: Be careful\n"
        assert out.err == ""

    def test_log_warning_tty_mode_has_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode log_warning() contains ANSI codes."""
        monkeypatch.setenv("WORKSPACE_AGENT", "0")
        log_warning("Be careful")
        out = capsys.readouterr().out
        assert "\x1b" in out

    def test_log_error_agent_mode_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode log_error() outputs 'ERROR: message' to stderr."""
        monkeypatch.setenv("WORKSPACE_AGENT", "1")
        log_error("Something failed")
        out = capsys.readouterr()
        assert out.out == ""
        assert out.err == "ERROR: Something failed\n"

    def test_log_error_tty_mode_has_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode log_error() contains ANSI codes."""
        monkeypatch.setenv("WORKSPACE_AGENT", "0")
        log_error("Something failed")
        out = capsys.readouterr().err
        assert "\x1b" in out
