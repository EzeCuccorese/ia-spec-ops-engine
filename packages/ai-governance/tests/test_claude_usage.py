from __future__ import annotations

from datetime import date

from ai_governance.telemetry.claude_usage import ClaudeUsageCalculator


def test_count_business_days() -> None:
    # September 2026 starts on Tuesday (Sept 1) and ends on Wednesday (Sept 30)
    # Total days = 30. Saturdays = 4 (5, 12, 19, 26), Sundays = 4 (6, 13, 20, 27)
    # Total business days = 30 - 8 = 22
    total = ClaudeUsageCalculator.count_business_days(2026, 9)
    assert total == 22

    # Up to Friday Sept 4 (days 1, 2, 3, 4 are Tue, Wed, Thu, Fri = 4 days)
    elapsed = ClaudeUsageCalculator.count_business_days(2026, 9, end_day=4)
    assert elapsed == 4


def test_ritmo_pacing_under_budget() -> None:
    # Budget $110, target date Sept 4 2026 (day 4 of 22 b-days)
    # Expected spend = 110 * (4 / 22) = $20.00
    stat = ClaudeUsageCalculator.calculate_pace(
        monthly_budget_usd=110.0,
        actual_spend_usd=15.0,
        target_date=date(2026, 9, 4),
    )
    assert stat.total_business_days == 22
    assert stat.elapsed_business_days == 4
    assert stat.days_remaining == 18
    assert round(stat.expected_spend_usd, 2) == 20.00
    assert stat.actual_spend_usd == 15.00
    assert stat.variance_usd == -5.00
    assert stat.is_under_budget is True
    assert "OK" in stat.status_label
    assert "margin" in stat.status_label


def test_ritmo_pacing_over_budget() -> None:
    stat = ClaudeUsageCalculator.calculate_pace(
        monthly_budget_usd=110.0,
        actual_spend_usd=30.0,
        target_date=date(2026, 9, 4),
    )
    assert stat.is_under_budget is False
    assert stat.variance_usd == 10.00
    assert stat.days_remaining == 18
    assert "EXCEEDED" in stat.status_label
    assert "variance" in stat.status_label


def test_count_business_days_boundary_conditions() -> None:
    # start_day > last_day
    assert ClaudeUsageCalculator.count_business_days(2026, 9, start_day=15, end_day=10) == 0

    # start_day < 1 clamped to 1
    assert ClaudeUsageCalculator.count_business_days(2026, 9, start_day=-5, end_day=4) == 4

    # end_day < 1 returns 0
    assert ClaudeUsageCalculator.count_business_days(2026, 9, start_day=1, end_day=0) == 0
    assert ClaudeUsageCalculator.count_business_days(2026, 9, start_day=1, end_day=-10) == 0

    # start_day beyond month end returns 0
    assert ClaudeUsageCalculator.count_business_days(2026, 9, start_day=35) == 0

    # Last business day of month: days_remaining is 0
    last_day_stat = ClaudeUsageCalculator.calculate_pace(
        monthly_budget_usd=100.0,
        actual_spend_usd=90.0,
        target_date=date(2026, 9, 30),
    )
    assert last_day_stat.elapsed_business_days == 22
    assert last_day_stat.days_remaining == 0
