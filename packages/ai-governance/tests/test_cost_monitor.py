from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.telemetry.cost_monitor import CostMonitor
from ai_governance.telemetry.prices import PriceCatalog


def test_price_catalog_fallback_and_models() -> None:
    pin, pout = PriceCatalog.get_price("claude-sonnet-4-6")
    assert pin == 3.0
    assert pout == 15.0

    pin_unknown, pout_unknown = PriceCatalog.get_price("unknown-experimental-model")
    assert pin_unknown == 2.0
    assert pout_unknown == 10.0


def test_scan_transcripts(tmp_path: Path) -> None:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir(parents=True)
    jsonl_file = project_dir / "session.jsonl"

    sample_entry = {
        "timestamp": "2026-09-04T12:00:00Z",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 10_000,
                "output_tokens": 2_000,
                "cache_read_input_tokens": 5_000,
                "cache_creation_input_tokens": 1_000,
            },
        },
    }
    jsonl_file.write_text(json.dumps(sample_entry) + "\n", encoding="utf-8")

    monitor = CostMonitor(projects_dir=tmp_path)
    res = monitor.scan_transcripts()

    assert res["total_tokens"] == 18_000
    assert res["total_cost_usd"] > 0
    assert "2026-09-04" in res["by_day"]


def test_init_rejects_non_positive_calibration() -> None:
    with pytest.raises(ValueError, match="Calibration must be greater than zero"):
        CostMonitor(calibration=0)


def test_calibration_factor_rejects_non_positive_estimated() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        CostMonitor.calibration_factor(estimated=0, actual=10)


def test_calibration_factor_rejects_negative_actual() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        CostMonitor.calibration_factor(estimated=10, actual=-1)


def test_day_handles_naive_timestamp_using_local_time() -> None:
    # No timezone suffix: `_day` falls back to treating it as UTC via replace(tzinfo=UTC).
    day = CostMonitor._day("2026-09-04T12:00:00", local_time=True)
    assert day is not None


def test_day_returns_none_for_unparseable_timestamp() -> None:
    assert CostMonitor._day("not-a-timestamp", local_time=False) is None


def test_day_returns_none_for_empty_timestamp() -> None:
    assert CostMonitor._day("", local_time=False) is None


def test_scan_transcripts_missing_projects_dir_returns_zero_totals(tmp_path: Path) -> None:
    monitor = CostMonitor(projects_dir=tmp_path / "does-not-exist")
    result = monitor.scan_transcripts()
    assert result["total_cost_usd"] == 0.0
    assert result["by_day"] == {}


def test_scan_transcripts_skips_lines_without_usage_key(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    jsonl_file.write_text('{"type": "assistant", "no_usage_here": true}\n', encoding="utf-8")
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts()
    assert result["total_cost_usd"] == 0.0


def test_scan_transcripts_skips_malformed_json_lines(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    jsonl_file.write_text('{"usage": not valid json\n', encoding="utf-8")
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts()
    assert result["total_cost_usd"] == 0.0


def test_scan_transcripts_skips_non_assistant_event_types(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    entry = {
        "type": "user",
        "timestamp": "2026-09-04T12:00:00Z",
        "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 100}},
    }
    jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts()
    assert result["total_cost_usd"] == 0.0


def test_scan_transcripts_skips_non_dict_usage(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    entry = {
        "timestamp": "2026-09-04T12:00:00Z",
        "message": {"model": "claude-sonnet-4-6", "usage": "not-a-dict"},
    }
    jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts()
    assert result["total_cost_usd"] == 0.0


def test_scan_transcripts_skips_all_zero_usage_events(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    entry = {
        "timestamp": "2026-09-04T12:00:00Z",
        "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 0}},
    }
    jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts()
    assert result["total_cost_usd"] == 0.0


def test_scan_transcripts_skips_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    jsonl_file.write_text('{"usage": {}}\n', encoding="utf-8")

    real_open = open

    def broken_open(path: object, *args: object, **kwargs: object) -> object:
        if str(path).endswith("session.jsonl"):
            raise OSError("simulated unreadable file")
        return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("builtins.open", broken_open)
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts()
    assert result["total_cost_usd"] == 0.0


def test_get_summary_report_includes_price_cache_age(tmp_path: Path) -> None:
    cache = tmp_path / "prices.json"
    cache.write_text(
        json.dumps({"fetched_at": "2020-01-01T00:00:00+00:00", "prices": {}}), encoding="utf-8"
    )
    monitor = CostMonitor(projects_dir=tmp_path, price_cache_path=cache)
    report = monitor.get_summary_report(100.0)
    assert report["price_cache_age_days"] is not None


def test_get_summary_report_without_price_cache_path(tmp_path: Path) -> None:
    monitor = CostMonitor(projects_dir=tmp_path)
    report = monitor.get_summary_report(100.0)
    assert report["price_cache_age_days"] is None


def test_scan_transcripts_deduplicates_repeated_event_ids(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    entry = {
        "id": "evt-dup",
        "timestamp": "2026-09-04T12:00:00Z",
        "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 100}},
    }
    line = json.dumps(entry) + "\n"
    jsonl_file.write_text(line + line, encoding="utf-8")
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts()
    assert result["tokens"]["input"] == 100


def test_scan_transcripts_skips_events_outside_date_range(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    jsonl_file = project_dir / "session.jsonl"
    entry = {
        "timestamp": "2026-01-01T12:00:00Z",
        "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 100}},
    }
    jsonl_file.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monitor = CostMonitor(projects_dir=tmp_path)
    result = monitor.scan_transcripts(since_iso_date="2026-09-01")
    assert result["total_cost_usd"] == 0.0


def test_scan_transcripts_tracks_effort_and_fast_calls(tmp_path: Path) -> None:
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    entries = [
        {
            "timestamp": "2026-09-04T12:00:00Z",
            "requestId": "a",
            "perTurnEffort": "high",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 1_000,
                    "output_tokens_details": {"thinking_tokens": 400},
                    "speed": "fast",
                },
            },
        },
        {
            "timestamp": "2026-09-04T13:00:00Z",
            "requestId": "b",
            "message": {"model": "claude-sonnet-4-6", "usage": {"output_tokens": 500}},
        },
    ]
    (project_dir / "s.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    res = CostMonitor(projects_dir=tmp_path).scan_transcripts()

    day = res["by_effort"]["2026-09-04"]
    assert day["high"]["output"] == 1_000 and day["high"]["thinking"] == 400
    assert day["unknown"]["output"] == 500
    assert res["fast_calls"] == 1
    merged = CostMonitor.merge_effort(res["by_effort"], lambda d: d.startswith("2026-09"))
    assert merged["high"]["cost"] == pytest.approx(day["high"]["cost"])
    assert CostMonitor.merge_effort(res["by_effort"], lambda d: False) == {}
