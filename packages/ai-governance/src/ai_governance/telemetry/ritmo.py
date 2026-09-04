"""
ritmo.py — Business-day budget pacing calculator.
Inspired by GHDominguez/ritmo: distributes monthly allowance across working days (Mon-Fri)
to evaluate real-time pace and spending variance.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class RitmoStatus:
    year: int
    month: int
    day: int
    total_business_days: int
    elapsed_business_days: int
    pace_ratio: float
    expected_spend_usd: float
    actual_spend_usd: float
    variance_usd: float
    is_under_budget: bool
    status_label: str


class RitmoCalculator:
    @staticmethod
    def count_business_days(year: int, month: int, start_day: int = 1, end_day: int | None = None) -> int:
        """Counts Monday-Friday days within [start_day, end_day] of the given year/month."""
        num_days = calendar.monthrange(year, month)[1]
        last_day = min(num_days, end_day if end_day is not None else num_days)

        count = 0
        for d in range(start_day, last_day + 1):
            dt = date(year, month, d)
            if dt.weekday() < 5:  # 0=Monday, 4=Friday
                count += 1
        return count

    @classmethod
    def calculate_pace(
        cls,
        monthly_budget_usd: float,
        actual_spend_usd: float = 0.0,
        target_date: date | None = None,
    ) -> RitmoStatus:
        target = target_date or datetime.now().date()
        total_b_days = cls.count_business_days(target.year, target.month)
        elapsed_b_days = cls.count_business_days(target.year, target.month, end_day=target.day)

        pace_ratio = elapsed_b_days / total_b_days if total_b_days > 0 else 0.0
        expected_spend = monthly_budget_usd * pace_ratio
        variance = actual_spend_usd - expected_spend
        is_under = variance <= 0.0

        if is_under:
            status_label = f"OK ({-variance:+.2f} USD margin)"
        else:
            status_label = f"EXCEEDED ({variance:+.2f} USD variance)"

        return RitmoStatus(
            year=target.year,
            month=target.month,
            day=target.day,
            total_business_days=total_b_days,
            elapsed_business_days=elapsed_b_days,
            pace_ratio=pace_ratio,
            expected_spend_usd=expected_spend,
            actual_spend_usd=actual_spend_usd,
            variance_usd=variance,
            is_under_budget=is_under,
            status_label=status_label,
        )
