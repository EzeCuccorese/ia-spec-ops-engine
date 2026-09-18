"""Tests for telemetry CLI output within budget constraints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.telemetry.cli import main as telemetry_main


class TestTelemetryThresholdsOutput:
    """Test telemetry thresholds command output budgets."""

    def test_thresholds_json_under_budget(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """telemetry thresholds --json output ≤ 2000 chars, no ANSI."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        # Create empty usage directory
        (tmp_path / "usage").mkdir(exist_ok=True)

        telemetry_main(["thresholds", "--json"])
        out = capsys.readouterr().out

        # May be non-zero if no data exists, but output should be bounded
        assert len(out) <= 2000, f"Output {len(out)} chars exceeds budget"
        assert "\x1b" not in out


class TestTelemetryUsageOutput:
    """Test telemetry usage command output budgets."""

    def test_usage_json_under_budget_with_default_budget(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """telemetry usage --json output ≤ 2000 chars with default budget."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        # Create empty usage directory
        (tmp_path / "usage").mkdir(exist_ok=True)

        telemetry_main(["usage", "--json"])
        out = capsys.readouterr().out

        # Tolerate non-zero return for empty data, but check output size
        assert len(out) <= 2000, f"Output {len(out)} chars exceeds budget"
        assert "\x1b" not in out

    def test_usage_json_with_budget_param(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """telemetry usage --json with --budget 4000 under budget."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        (tmp_path / "usage").mkdir(exist_ok=True)

        telemetry_main(["usage", "--json", "--budget", "4000"])
        out = capsys.readouterr().out

        # Tolerate non-zero return for empty data, check output size
        assert len(out) <= 4000, f"Output {len(out)} chars exceeds budget"
        assert "\x1b" not in out


class TestTelemetryReportOutput:
    """Test telemetry report command output budgets."""

    def test_report_json_under_budget(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """telemetry report --json output ≤ 2000 chars, no ANSI."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        (tmp_path / "usage").mkdir(exist_ok=True)

        telemetry_main(["report", "--json"])
        out = capsys.readouterr().out

        assert len(out) <= 2000, f"Output {len(out)} chars exceeds budget"
        assert "\x1b" not in out


class TestTelemetryJsonValid:
    """Test that telemetry JSON output is valid when non-empty."""

    def test_thresholds_json_parseable(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """telemetry thresholds --json produces valid JSON when it has output."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        (tmp_path / "usage").mkdir(exist_ok=True)

        telemetry_main(["thresholds", "--json"])
        out = capsys.readouterr().out

        if out.strip():
            data = json.loads(out)
            assert isinstance(data, dict)


class TestTelemetryNoAnsi:
    """Test that telemetry commands never emit ANSI in agent mode."""

    def test_thresholds_text_no_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """telemetry thresholds text output has no ANSI codes."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        (tmp_path / "usage").mkdir(exist_ok=True)

        telemetry_main(["thresholds"])
        out = capsys.readouterr().out

        assert "\x1b" not in out

    def test_usage_text_no_ansi(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """telemetry usage text output has no ANSI codes."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        (tmp_path / "usage").mkdir(exist_ok=True)

        telemetry_main(["usage"])
        out = capsys.readouterr().out

        assert "\x1b" not in out
