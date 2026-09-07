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


def test_format_statusline_monthly_spend_resolution() -> None:
    # 1. Explicit monthly_spend_usd argument overrides session cost and payload
    payload = {
        "cost": {"total_cost_usd": 1.0, "monthly_cost_usd": 50.0},
        "monthly_spend_usd": 75.0,
    }
    # Budget $100, monthly_spend_usd=$500 (definitely EXCEEDED)
    res_arg = format_statusline(
        payload, include_ritmo=True, monthly_budget=100.0, monthly_spend_usd=500.0
    )
    assert "$1.00" in res_arg  # session cost displayed
    assert "EXCEEDED" in res_arg

    # 2. payload["monthly_spend_usd"] used when no arg is provided
    payload_top = {
        "cost": {"total_cost_usd": 1.0, "monthly_cost_usd": 5.0},
        "monthly_spend_usd": 500.0,
    }
    res_top = format_statusline(payload_top, include_ritmo=True, monthly_budget=100.0)
    assert "$1.00" in res_top
    assert "EXCEEDED" in res_top

    # 3. payload["cost"]["monthly_cost_usd"] used when no top-level spend is provided
    payload_nested = {
        "cost": {"total_cost_usd": 1.0, "monthly_cost_usd": 500.0},
    }
    res_nested = format_statusline(payload_nested, include_ritmo=True, monthly_budget=100.0)
    assert "$1.00" in res_nested
    assert "EXCEEDED" in res_nested

    # 4. Fallback to total_cost_usd ($1.00) when no monthly spend is provided (OK/under budget)
    payload_fallback = {
        "cost": {"total_cost_usd": 1.0},
    }
    res_fallback = format_statusline(payload_fallback, include_ritmo=True, monthly_budget=100.0)
    assert "$1.00" in res_fallback
    assert "OK" in res_fallback
