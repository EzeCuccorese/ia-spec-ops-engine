"""Coverage tests for ai_governance.telemetry.cli."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.telemetry import cli as telemetry_cli
from ai_governance.telemetry.cli import main as telemetry_main


def _set_usage_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    usage_dir = tmp_path / "usage"
    usage_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("SPECOPS_AGENT", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SPECOPS_USAGE_DIR", str(usage_dir))
    monkeypatch.delenv("CLAUDE_USAGE_DIR", raising=False)
    return usage_dir


def test_runtime_dir_prefers_specops_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "a"))
    monkeypatch.setenv("CLAUDE_USAGE_DIR", str(tmp_path / "b"))
    assert telemetry_cli.runtime_dir() == tmp_path / "a"


def test_runtime_dir_falls_back_to_claude_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SPECOPS_USAGE_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_USAGE_DIR", str(tmp_path / "b"))
    assert telemetry_cli.runtime_dir() == tmp_path / "b"


def test_runtime_dir_falls_back_to_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SPECOPS_USAGE_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_USAGE_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert telemetry_cli.runtime_dir() == tmp_path / ".specops" / "usage-monitor"


def test_ritmo_command_prints_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    result = telemetry_main(["ritmo", "--budget", "100", "--spent", "10"])
    out = capsys.readouterr().out
    assert result == 0
    assert "Monthly budget" in out


def test_usage_report_with_price_cache_recent_and_model_breakdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Exercises the non-JSON usage report with a recent price cache and model rows."""
    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("SPECOPS_AGENT", "0")
    cache = usage_dir / "prices-cache.json"
    from datetime import UTC, datetime

    cache.write_text(
        json.dumps({"fetched_at": datetime.now(UTC).isoformat(), "prices": {}}),
        encoding="utf-8",
    )
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    entry = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT12:00:00Z"),
        "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 1000}},
    }
    (projects_dir / "s.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        telemetry_cli,
        "_monitor",
        lambda base, config: telemetry_cli.CostMonitor(
            projects_dir=projects_dir,
            price_cache_path=base / "prices-cache.json",
            calibration=config.calibration,
            holidays=config.holidays,
        ),
    )
    result = telemetry_main(["usage"])
    out = capsys.readouterr().out
    assert result == 0
    assert "Claude usage estimate" in out
    assert "Model claude-sonnet-4-6" in out
    assert "days old" in out


def test_usage_report_with_stale_price_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("SPECOPS_AGENT", "0")
    cache = usage_dir / "prices-cache.json"
    cache.write_text(
        json.dumps({"fetched_at": "2020-01-01T00:00:00+00:00", "prices": {}}), encoding="utf-8"
    )
    result = telemetry_main(["usage"])
    out = capsys.readouterr().out
    assert result == 0
    assert "run telemetry prices update" in out


def test_usage_report_without_price_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("SPECOPS_AGENT", "0")
    result = telemetry_main(["usage"])
    out = capsys.readouterr().out
    assert result == 0
    assert "not available; using bundled fallback" in out


def test_calibrate_command_saves_factor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(
        telemetry_cli.CostMonitor,
        "scan_transcripts",
        lambda self, since, until: {"total_cost_usd": 10.0},
    )
    result = telemetry_main(
        ["calibrate", "--from", "2026-09-01", "--to", "2026-09-14", "--actual", "20"]
    )
    out = capsys.readouterr().out
    assert result == 0
    assert "Calibration saved: 2.000" in out
    saved = json.loads((usage_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["calibration"] == pytest.approx(2.0)


def test_prices_update_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(
        telemetry_cli.PriceCatalog,
        "refresh_cache",
        staticmethod(lambda path, url: {"prices": {"model-a": {"input": 1, "output": 2}}}),
    )
    result = telemetry_main(["prices", "update"])
    out = capsys.readouterr().out
    assert result == 0
    assert "Updated 1 direct Anthropic model prices." in out


def test_thresholds_command_with_notify_and_macos_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    config = {"monthly_budget_usd": 10.0, "notify_macos": True, "daily_thresholds_pct": [1]}
    (usage_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(
        telemetry_cli,
        "_monitor",
        lambda base, cfg: telemetry_cli.CostMonitor(
            projects_dir=tmp_path / "nonexistent", price_cache_path=None, calibration=1.0
        ),
    )

    captured: dict[str, str] = {}

    def fake_notify(title: str, message: str) -> bool:
        captured["title"] = title
        captured["message"] = message
        return True

    monkeypatch.setattr(telemetry_cli, "notify_macos", fake_notify)

    def fake_evaluate(summary, cfg, state, *, today=None):
        return (["Daily estimated usage crossed 1% ($0.00)."], {"day_notified": [1]})

    monkeypatch.setattr(telemetry_cli.ThresholdTracker, "evaluate", staticmethod(fake_evaluate))

    result = telemetry_main(["thresholds", "--notify"])
    out = capsys.readouterr().out
    assert result == 0
    assert "Daily estimated usage crossed" in out
    assert captured["title"] == "Claude usage estimate"


def test_thresholds_command_no_messages_and_no_print(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    result = telemetry_main(["thresholds"])
    out = capsys.readouterr().out
    assert result == 0
    assert out == ""


def test_no_command_prints_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    result = telemetry_main([])
    out = capsys.readouterr().out
    assert result == 0
    assert "usage" in out.lower()


def test_main_reports_error_on_invalid_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    (usage_dir / "config.json").write_text(json.dumps({"monthly_budget_usd": -5}), encoding="utf-8")
    result = telemetry_main(["ritmo"])
    err = capsys.readouterr().err
    assert result == 1
    assert "Telemetry error" in err
