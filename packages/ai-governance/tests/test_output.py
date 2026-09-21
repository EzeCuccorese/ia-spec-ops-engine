"""Tests for ai_governance.output — Agent-aware output primitives."""

from __future__ import annotations

import sys

import pytest
from ai_governance.output import (
    emit_json,
    emit_kv,
    emit_rows,
    emit_status,
    emit_text,
    is_agent_mode,
    truncate,
)


class TestIsAgentMode:
    """Test is_agent_mode() behavior under different environment conditions."""

    def test_agent_mode_forced_on_with_env_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SPECOPS_AGENT=1 forces agent mode ON even if stdout is a TTY."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert is_agent_mode() is True

    def test_agent_mode_forced_off_with_env_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SPECOPS_AGENT=0 forces agent mode OFF even if not a TTY."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert is_agent_mode() is False

    def test_agent_mode_off_when_tty_and_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset env + TTY → agent mode OFF."""
        monkeypatch.delenv("SPECOPS_AGENT", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
        assert is_agent_mode() is False

    def test_agent_mode_on_when_not_tty_and_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset env + not TTY → agent mode ON."""
        monkeypatch.delenv("SPECOPS_AGENT", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        assert is_agent_mode() is True


class TestTruncate:
    """Test truncate() line and character limits."""

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

    def test_truncate_line_cut_with_hint(self) -> None:
        """Line truncation with a hint appends 'more: <hint>'."""
        lines = [f"line{i}" for i in range(30)]
        text = "\n".join(lines)
        result = truncate(text, max_lines=5, max_chars=1500, more_hint="see all")
        result_lines = result.split("\n")
        assert len(result_lines) == 5
        assert result_lines[-1] == "more: see all"

    def test_truncate_char_cut_respects_budget(self) -> None:
        """Exceeding max_chars cuts at line boundary and adds 'more:'."""
        lines = ["x" * 200 for _ in range(20)]
        text = "\n".join(lines)
        result = truncate(text, max_lines=100, max_chars=500)
        assert len(result) <= 500
        assert result.split("\n")[-1].startswith("more:")

    def test_truncate_char_cut_with_hint(self) -> None:
        """Character truncation with hint."""
        lines = ["y" * 300 for _ in range(10)]
        text = "\n".join(lines)
        result = truncate(text, max_lines=100, max_chars=500, more_hint="next page")
        assert len(result) <= 500
        assert result.split("\n")[-1] == "more: next page"

    def test_truncate_empty_hint_is_exact(self) -> None:
        """Empty hint produces exactly 'more:' with no space."""
        text = "\n".join(["x" * 200 for _ in range(20)])
        result = truncate(text, max_lines=100, max_chars=300, more_hint="")
        assert result.split("\n")[-1] == "more:"

    def test_truncate_never_cuts_mid_line(self) -> None:
        """Truncation stops at line boundaries, never in the middle."""
        lines = ["line" + str(i) for i in range(20)]
        text = "\n".join(lines)
        result = truncate(text, max_lines=5, max_chars=1000)
        for line in result.split("\n")[:-1]:
            assert "\n" not in line

    def test_truncate_empty_candidate_lines_skips_budget_loop(self) -> None:
        """An empty candidate list (max_lines<=1, negative max_chars) skips the budget loop."""
        result = truncate("", max_lines=1, max_chars=-1)
        assert result == "more:"


class TestEmitRows:
    """Test emit_rows() in both agent and TTY modes."""

    def test_emit_rows_agent_mode_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode emits title, headers, and rows joined with ' | '."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        rows = [("a", "b", "c"), ("d", "e", "f")]
        emit_rows(rows, headers=("H1", "H2", "H3"), title="Table")
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert lines[0] == "Table"
        assert lines[1] == "H1 | H2 | H3"
        assert lines[2] == "a | b | c"
        assert lines[3] == "d | e | f"

    def test_emit_rows_agent_mode_no_title(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode without title omits title line."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        rows = [("x", "y")]
        emit_rows(rows, headers=("C1", "C2"))
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert lines[0] == "C1 | C2"
        assert lines[1] == "x | y"

    def test_emit_rows_agent_mode_full_true_no_truncate(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with full=True never truncates, even with many rows."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        rows = [(f"r{i}", f"d{i}") for i in range(50)]
        emit_rows(rows, headers=("ID", "Data"), full=True)
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert "more:" not in out
        assert len(lines) == 51  # header + 50 rows

    def test_emit_rows_agent_mode_full_false_truncates(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with full=False truncates large output and adds 'more:'."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        rows = [(f"r{i}", f"d{i}") for i in range(50)]
        emit_rows(rows, headers=("ID", "Data"), full=False)
        out = capsys.readouterr().out
        assert "more:" in out

    def test_emit_rows_agent_mode_no_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode output contains no ANSI escape sequences."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        rows = [("cell1", "cell2")]
        emit_rows(rows, headers=("H1", "H2"), title="Test")
        out = capsys.readouterr().out
        assert "\x1b" not in out

    def test_emit_rows_tty_mode_prints_rich_table(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode renders a rich table with headers and a title."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        rows = [("a", "b"), ("c", "d")]
        emit_rows(rows, headers=("H1", "H2"), title="Table")
        out = capsys.readouterr().out
        assert "Table" in out
        assert "H1" in out
        assert "a" in out

    def test_emit_rows_agent_mode_no_headers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with no headers skips the headers line (if-headers branch)."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        rows = [("x", "y")]
        emit_rows(rows)
        out = capsys.readouterr().out
        assert out.strip() == "x | y"

    def test_emit_rows_tty_mode_no_headers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode with no headers still renders rows (headers-or-[] branch)."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        rows = [("x", "y")]
        emit_rows(rows)
        out = capsys.readouterr().out
        assert "x" in out


class TestEmitKv:
    """Test emit_kv() in agent mode."""

    def test_emit_kv_agent_mode_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode emits 'key: value' lines."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        pairs = [("name", "Alice"), ("age", "30"), ("city", "NYC")]
        emit_kv(pairs)
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert lines[0] == "name: Alice"
        assert lines[1] == "age: 30"
        assert lines[2] == "city: NYC"

    def test_emit_kv_agent_mode_with_title(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with title prepends title line."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        pairs = [("key1", "val1")]
        emit_kv(pairs, title="My Data")
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        assert lines[0] == "My Data"
        assert lines[1] == "key1: val1"

    def test_emit_kv_agent_mode_full_false_truncates(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with full=False truncates large KV output."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        pairs = [(f"k{i}", f"v{i}" * 50) for i in range(50)]
        emit_kv(pairs, full=False)
        out = capsys.readouterr().out
        assert "more:" in out

    def test_emit_kv_agent_mode_full_true_no_truncate(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with full=True never truncates."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        pairs = [(f"k{i}", f"v{i}" * 50) for i in range(50)]
        emit_kv(pairs, full=True)
        out = capsys.readouterr().out
        assert "more:" not in out

    def test_emit_kv_tty_mode_prints_rich_table(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode renders a two-column rich table."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        pairs = [("name", "Alice")]
        emit_kv(pairs, title="Info")
        out = capsys.readouterr().out
        assert "name" in out
        assert "Alice" in out


class TestEmitJson:
    """Test emit_json() in agent vs TTY mode."""

    def test_emit_json_agent_mode_dense(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode emits dense JSON: single line, no spaces after ':' or ','."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        data = {"key": "value", "num": 42, "nested": {"a": 1}}
        emit_json(data)
        out = capsys.readouterr().out.strip()
        assert "\n" not in out
        assert ": " not in out
        assert ", " not in out

    def test_emit_json_tty_mode_indented(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode emits indented JSON with indent=2."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        data = {"key": "value", "nested": {"a": 1}}
        emit_json(data)
        out = capsys.readouterr().out
        assert "\n" in out
        assert "  " in out


class TestEmitStatus:
    """Test emit_status() in agent mode."""

    def test_emit_status_ok_to_stdout(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode 'ok' status goes to stdout as 'OK: message'."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        emit_status("ok", "Operation succeeded")
        out = capsys.readouterr()
        assert out.out == "OK: Operation succeeded\n"
        assert out.err == ""

    def test_emit_status_warn_to_stdout(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode 'warn' status goes to stdout as 'WARN: message'."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        emit_status("warn", "Be careful")
        out = capsys.readouterr()
        assert out.out == "WARN: Be careful\n"
        assert out.err == ""

    def test_emit_status_info_to_stdout(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode 'info' status goes to stdout as 'INFO: message'."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        emit_status("info", "FYI")
        out = capsys.readouterr()
        assert out.out == "INFO: FYI\n"
        assert out.err == ""

    def test_emit_status_error_to_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode 'error' status goes to stderr as 'ERROR: message'."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        emit_status("error", "Failed")
        out = capsys.readouterr()
        assert out.out == ""
        assert out.err == "ERROR: Failed\n"

    def test_emit_status_tty_mode_ok(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode renders a styled status line for 'ok' via the rich console."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        emit_status("ok", "All good")
        out = capsys.readouterr().out
        assert "All good" in out

    def test_emit_status_tty_mode_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode renders 'error' status to stdout too (only agent mode uses stderr)."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        emit_status("error", "Broken")
        out = capsys.readouterr()
        assert "Broken" in out.out
        assert out.err == ""


class TestEmitText:
    """Test emit_text() in agent mode."""

    def test_emit_text_agent_mode_full_false_truncates(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with full=False truncates long text."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        text = "\n".join(["line" + str(i) for i in range(100)])
        emit_text(text, full=False)
        out = capsys.readouterr().out
        assert "more:" in out

    def test_emit_text_agent_mode_full_true_no_truncate(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Agent mode with full=True never truncates."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        text = "\n".join(["line" + str(i) for i in range(100)])
        emit_text(text, full=True)
        out = capsys.readouterr().out
        assert "more:" not in out

    def test_emit_text_tty_mode_prints_via_console(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """TTY mode prints text via the rich console, untruncated."""
        monkeypatch.setenv("SPECOPS_AGENT", "0")
        text = "\n".join(["line" + str(i) for i in range(100)])
        emit_text(text)
        out = capsys.readouterr().out
        assert "line99" in out
