from __future__ import annotations

import time

from ai_governance.telemetry.statusline import format_statusline, format_tokens


def test_format_tokens() -> None:
    assert format_tokens(500) == "500"
    assert format_tokens(1500) == "1.5k"
    assert format_tokens(2_500_000) == "2.5M"


def test_format_statusline_complete_payload() -> None:
    now = int(time.time())
    payload = {
        "cost": {"total_cost_usd": 0.45},
        "context_window": {
            "total_input_tokens": 12500,
            "total_output_tokens": 1500,
            "used_percentage": 25.4,
        },
        "rate_limits": {
            "five_hour": {
                "used_percentage": 40.0,
                "resets_at": now + 7200,  # 2 hours
            }
        },
    }
    res = format_statusline(payload)
    assert "$0.45" in res
    assert "14.0k" in res
    assert "25% ctx" in res
    assert "40%" in res
    assert "resets 2h" in res


def test_format_statusline_with_ritmo() -> None:
    payload = {
        "cost": {"total_cost_usd": 12.0},
        "context_window": {
            "total_input_tokens": 1000,
            "total_output_tokens": 100,
            "used_percentage": 10.0,
        },
    }
    res = format_statusline(payload, include_ritmo=True, monthly_budget=200.0)
    assert "$12.00" in res
    assert "ritmo:" in res


def test_format_statusline_empty_or_minimal() -> None:
    assert format_statusline({}) != ""
    assert "$0.00" in format_statusline({})
