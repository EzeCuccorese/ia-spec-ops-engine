"""Coverage tests for ai_governance.telemetry.state."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
from ai_governance.telemetry.state import (
    TelemetryConfig,
    ThresholdTracker,
    atomic_json_write,
    notify_macos,
)


def test_atomic_json_write_cleans_up_temp_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `Path.replace` fails, the leftover temp file is removed."""
    target = tmp_path / "sub" / "state.json"

    def boom(self: Path, _dest: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_json_write(target, {"a": 1})
    leftovers = list((tmp_path / "sub").iterdir())
    assert leftovers == []


def test_config_holidays_parses_iso_dates() -> None:
    config = TelemetryConfig(holiday_dates=("2026-01-01", "2026-12-25"))
    assert config.holidays == {date(2026, 1, 1), date(2026, 12, 25)}


def test_config_holidays_invalid_date_raises() -> None:
    config = TelemetryConfig(holiday_dates=("not-a-date",))
    with pytest.raises(ValueError, match="Invalid holiday date"):
        _ = config.holidays


def test_effective_monthly_limit_with_hard_limit_below_budget() -> None:
    config = TelemetryConfig(monthly_budget_usd=100.0, monthly_hard_limit_usd=40.0)
    assert config.effective_monthly_limit == 40.0


def test_effective_monthly_limit_with_hard_limit_above_budget() -> None:
    config = TelemetryConfig(monthly_budget_usd=100.0, monthly_hard_limit_usd=500.0)
    assert config.effective_monthly_limit == 100.0


def test_config_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = TelemetryConfig.load(tmp_path / "missing.json")
    assert config == TelemetryConfig()


def test_config_load_non_dict_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        TelemetryConfig.load(path)


def test_config_load_coerces_thresholds_and_holidays(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "monthly_budget_usd": 200,
                "daily_thresholds_pct": [50.0, 90.0],
                "monthly_thresholds_pct": [80.0],
                "holiday_dates": ["2026-01-01"],
                "unknown_field": "ignored",
            }
        ),
        encoding="utf-8",
    )
    config = TelemetryConfig.load(path)
    assert config.daily_thresholds_pct == (50, 90)
    assert config.monthly_thresholds_pct == (80,)
    assert config.holiday_dates == ("2026-01-01",)
    assert config.monthly_budget_usd == 200


def test_config_load_rejects_non_positive_budget(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"monthly_budget_usd": 0}), encoding="utf-8")
    with pytest.raises(ValueError, match="greater than zero"):
        TelemetryConfig.load(path)


def test_config_load_rejects_non_positive_calibration(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"calibration": -1}), encoding="utf-8")
    with pytest.raises(ValueError, match="greater than zero"):
        TelemetryConfig.load(path)


def test_config_save_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = TelemetryConfig(
        monthly_budget_usd=50.0,
        daily_thresholds_pct=(25, 75),
        monthly_thresholds_pct=(60,),
        holiday_dates=("2026-05-01",),
    )
    config.save(path)
    reloaded = TelemetryConfig.load(path)
    assert reloaded == config


def test_threshold_tracker_evaluate_monthly_crossing() -> None:
    config = TelemetryConfig(monthly_budget_usd=100, monthly_thresholds_pct=(50, 90))
    messages, state = ThresholdTracker.evaluate(
        {"today_cost_usd": 1, "daily_budget_usd": 10, "month_cost_usd": 60},
        config,
        {},
        today=date(2026, 9, 14),
    )
    assert any("monthly" in message.lower() for message in messages)
    assert state["month_notified"] == [50]


def test_threshold_tracker_load_missing_file_returns_empty(tmp_path: Path) -> None:
    assert ThresholdTracker.load(tmp_path / "missing.json") == {}


def test_threshold_tracker_load_invalid_json_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")
    assert ThresholdTracker.load(path) == {}


def test_threshold_tracker_load_non_dict_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert ThresholdTracker.load(path) == {}


def test_threshold_tracker_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    ThresholdTracker.save(path, {"day": "2026-09-14", "day_notified": [50]})
    assert ThresholdTracker.load(path) == {"day": "2026-09-14", "day_notified": [50]}


def test_notify_macos_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert notify_macos('Title "Q"', "Message\\path") is True
    cmd = captured["cmd"]
    assert cmd[0] == "osascript"
    assert '\\"Q\\"' in cmd[2]


def test_notify_macos_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert notify_macos("Title", "Message") is False


def test_notify_macos_handles_missing_osascript(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("no osascript")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert notify_macos("Title", "Message") is False


def test_notify_macos_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert notify_macos("Title", "Message") is False
