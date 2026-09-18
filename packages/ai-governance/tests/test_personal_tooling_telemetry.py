"""Telemetry acceptance coverage for @s3 and @s4."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from ai_governance.telemetry.cost_monitor import CostMonitor
from ai_governance.telemetry.prices import PriceCatalog
from ai_governance.telemetry.ritmo import RitmoCalculator
from ai_governance.telemetry.state import TelemetryConfig, ThresholdTracker


def test_cost_monitor_prices_cache_tiers_server_tools_and_provenance(tmp_path: Path) -> None:
    cache = tmp_path / "prices.json"
    cache.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fetched_at": "2026-09-14T00:00:00+00:00",
                "prices": {"claude-test": {"input": 2.0, "output": 10.0}},
            }
        ),
        encoding="utf-8",
    )
    projects = tmp_path / "projects"
    projects.mkdir()
    event = {
        "id": "evt-1",
        "type": "assistant",
        "timestamp": "2026-09-14T10:00:00Z",
        "message": {
            "model": "claude-test",
            "usage": {
                "input_tokens": 1_000_000,
                "output_tokens": 100_000,
                "cache_read_input_tokens": 500_000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 100_000,
                    "ephemeral_1h_input_tokens": 200_000,
                },
                "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 3},
            },
        },
    }
    (projects / "s.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    result = CostMonitor(projects, price_cache_path=cache).scan_transcripts()
    expected = 2.0 + 1.0 + 0.1 + 0.25 + 0.8 + 0.05
    assert result["total_cost_usd"] == pytest.approx(expected)
    assert result["tokens"]["cache_write_5m"] == 100_000
    assert result["tokens"]["cache_write_1h"] == 200_000
    assert result["server_tools"] == {"web_search": 2, "web_fetch": 3}
    assert result["provenance"]["kind"] == "local_transcript_estimate"


def test_price_refresh_validates_before_replacing_cache(tmp_path: Path) -> None:
    target = tmp_path / "prices.json"
    target.write_text('{"keep": true}', encoding="utf-8")
    feed = {
        "claude-test": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 0.000002,
            "output_cost_per_token": 0.00001,
        },
        "vertex-claude": {
            "litellm_provider": "vertex_ai",
            "input_cost_per_token": 1,
            "output_cost_per_token": 1,
        },
    }
    PriceCatalog.refresh_cache(target, "https://prices.test/feed", fetcher=lambda _u, _t: feed)
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["prices"]["claude-test"] == {"input": 2.0, "output": 10.0}
    previous = target.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        PriceCatalog.refresh_cache(target, "x", fetcher=lambda _u, _t: {})
    assert target.read_text(encoding="utf-8") == previous


def test_calibration_and_thresholds_are_explicit() -> None:
    assert CostMonitor.calibration_factor(estimated=80, actual=100) == pytest.approx(1.25)
    cfg = TelemetryConfig(monthly_budget_usd=100, daily_thresholds_pct=(50, 90))
    messages, state = ThresholdTracker.evaluate(
        {"today_cost_usd": 6, "daily_budget_usd": 10, "month_cost_usd": 20},
        cfg,
        {},
        today=date(2026, 9, 14),
    )
    assert any("daily" in message.lower() for message in messages)
    assert state["day_notified"] == [50]
    assert (
        ThresholdTracker.evaluate(
            {"today_cost_usd": 6, "daily_budget_usd": 10, "month_cost_usd": 20},
            cfg,
            state,
            today=date(2026, 9, 14),
        )[0]
        == []
    )


def test_business_day_calendar_is_configurable() -> None:
    without_holiday = RitmoCalculator.calculate_pace(100, 10, target_date=date(2026, 9, 14))
    with_holiday = RitmoCalculator.calculate_pace(
        100,
        10,
        target_date=date(2026, 9, 14),
        holidays={date(2026, 9, 14)},
    )
    assert with_holiday.elapsed_business_days == without_holiday.elapsed_business_days - 1
