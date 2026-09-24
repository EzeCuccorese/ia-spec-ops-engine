"""
claude_usage.py — Business-day Claude spend pacing (claude-usage).
Distributes the monthly allowance across working days (Mon-Fri minus holidays)
to evaluate real-time pace and spending variance.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class ClaudeUsageStatus:
    year: int
    month: int
    day: int
    total_business_days: int
    elapsed_business_days: int
    days_remaining: int
    pace_ratio: float
    expected_spend_usd: float
    actual_spend_usd: float | None
    variance_usd: float | None
    is_under_budget: bool | None
    status_label: str


class ClaudeUsageCalculator:
    @staticmethod
    def count_business_days(
        year: int,
        month: int,
        start_day: int = 1,
        end_day: int | None = None,
        holidays: set[date] | None = None,
    ) -> int:
        """Counts Monday-Friday days within [start_day, end_day] of the given year/month."""
        num_days = calendar.monthrange(year, month)[1]
        if end_day is not None and end_day < 1:
            return 0
        effective_start = max(1, start_day)
        last_day = min(num_days, end_day if end_day is not None else num_days)
        if effective_start > last_day:
            return 0

        count = 0
        for d in range(effective_start, last_day + 1):
            dt = date(year, month, d)
            if dt.weekday() < 5 and dt not in (holidays or set()):  # 0=Monday, 4=Friday
                count += 1
        return count

    @classmethod
    def calculate_pace(
        cls,
        monthly_budget_usd: float,
        actual_spend_usd: float | None = None,
        target_date: date | None = None,
        holidays: set[date] | None = None,
    ) -> ClaudeUsageStatus:
        target = target_date or datetime.now().date()
        total_b_days = cls.count_business_days(target.year, target.month, holidays=holidays)
        elapsed_b_days = cls.count_business_days(
            target.year, target.month, end_day=target.day, holidays=holidays
        )
        days_remaining = max(0, total_b_days - elapsed_b_days)

        pace_ratio = elapsed_b_days / total_b_days if total_b_days > 0 else 0.0
        expected_spend = monthly_budget_usd * pace_ratio

        if actual_spend_usd is None:
            return ClaudeUsageStatus(
                year=target.year,
                month=target.month,
                day=target.day,
                total_business_days=total_b_days,
                elapsed_business_days=elapsed_b_days,
                days_remaining=days_remaining,
                pace_ratio=pace_ratio,
                expected_spend_usd=expected_spend,
                actual_spend_usd=None,
                variance_usd=None,
                is_under_budget=None,
                status_label="unknown",
            )

        variance = actual_spend_usd - expected_spend
        is_under = variance <= 0.0

        if is_under:
            status_label = f"OK ({-variance:+.2f} USD margin)"
        else:
            status_label = f"EXCEEDED ({variance:+.2f} USD variance)"

        return ClaudeUsageStatus(
            year=target.year,
            month=target.month,
            day=target.day,
            total_business_days=total_b_days,
            elapsed_business_days=elapsed_b_days,
            days_remaining=days_remaining,
            pace_ratio=pace_ratio,
            expected_spend_usd=expected_spend,
            actual_spend_usd=actual_spend_usd,
            variance_usd=variance,
            is_under_budget=is_under,
            status_label=status_label,
        )
