"""Coverage tests for ai_governance.telemetry.cli."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.telemetry import cli as telemetry_cli
from ai_governance.telemetry.cli import main as telemetry_main


def _set_usage_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    usage_dir = tmp_path / "state" / "telemetry"
    usage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    return usage_dir


def test_ritmo_command_prints_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    result = telemetry_main(["claude-usage", "--budget", "100", "--spent", "10"])
    out = capsys.readouterr().out
    assert result == 0
    assert "Monthly budget" in out


def test_usage_report_with_price_cache_recent_and_model_breakdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Exercises the non-JSON usage report with a recent price cache and model rows."""
    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "0")
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
    result = telemetry_main(["report"])
    out = capsys.readouterr().out
    assert result == 0
    assert "Claude usage estimate" in out
    assert "Model claude-sonnet-4-6" in out
    assert "days old" in out


def test_usage_report_with_stale_price_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "0")
    cache = usage_dir / "prices-cache.json"
    cache.write_text(
        json.dumps({"fetched_at": "2020-01-01T00:00:00+00:00", "prices": {}}), encoding="utf-8"
    )
    result = telemetry_main(["report"])
    out = capsys.readouterr().out
    assert result == 0
    assert "prices update" in out


def test_usage_report_without_price_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("AI_GOVERNANCE_AGENT", "0")
    result = telemetry_main(["report"])
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
    result = telemetry_main(["claude-usage"])
    err = capsys.readouterr().err
    assert result == 1
    assert "Telemetry error" in err


def test_runtime_dir_is_under_state_dir(monkeypatch, tmp_path) -> None:
    from ai_governance.telemetry import cli as telemetry_cli

    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path))
    assert telemetry_cli.runtime_dir() == tmp_path / "telemetry"


def test_format_effort_shares_and_thinking() -> None:
    text = telemetry_cli.format_effort(
        {
            "low": {"cost": 1.0, "output": 100, "thinking": 0},
            "high": {"cost": 3.0, "output": 100, "thinking": 50},
        }
    )
    assert text == "high $3.00 (75%, thinking 50%) | low $1.00 (25%)"
    assert telemetry_cli.format_effort({}) == ""


def test_statusline_uses_todays_hook_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from datetime import date

    usage_dir = _set_usage_dir(monkeypatch, tmp_path)
    (usage_dir / "config.json").write_text(json.dumps({"monthly_budget_usd": 750}))
    (usage_dir / "state.json").write_text(
        json.dumps({"day": date.today().isoformat(), "last_day_cost": 5, "last_month_cost": 150})
    )
    monkeypatch.setattr(
        telemetry_cli, "_monitor", lambda *a: pytest.fail("must not rescan transcripts")
    )
    assert telemetry_main(["statusline"]) == 0
    out = capsys.readouterr().out
    assert "today $5.00/" in out and "left $600" in out
    assert "month $150/" in out


def test_statusline_rescans_when_cache_is_stale_and_never_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _set_usage_dir(monkeypatch, tmp_path)
    assert telemetry_main(["statusline"]) == 0
    assert "today $0.00/" in capsys.readouterr().out

    def boom(*args: object) -> None:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(telemetry_cli, "_monitor", boom)
    assert telemetry_main(["statusline"]) == 0
    assert capsys.readouterr().out == ""


def test_report_warns_about_fast_calls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = {
        "today_cost_usd": 1.0,
        "month_cost_usd": 2.0,
        "daily_budget_usd": 3.0,
        "tokens": {"output": 1},
        "by_model": {},
        "effort_today": {"low": {"cost": 1.0, "output": 1, "thinking": 0}},
        "effort_month": {},
        "fast_calls": 2,
        "price_cache_age_days": 1,
    }
    telemetry_cli.show_usage_report(summary)
    captured = capsys.readouterr()
    assert "low $1.00 (100%)" in captured.out
    assert "2 fast-mode calls" in captured.out + captured.err
