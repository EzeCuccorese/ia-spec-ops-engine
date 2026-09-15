"""Local Claude transcript cost estimator with explicit provenance."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .prices import PriceCatalog
from .ritmo import RitmoCalculator

WEB_SEARCH_USD = 10.0 / 1000.0
WEB_FETCH_USD = 10.0 / 1000.0


class CostMonitor:
    def __init__(
        self,
        projects_dir: Path | None = None,
        *,
        price_cache_path: Path | None = None,
        calibration: float = 1.0,
        holidays: set[date] | None = None,
    ) -> None:
        self.projects_dir = projects_dir or (Path.home() / ".claude" / "projects")
        self.price_cache_path = price_cache_path
        if calibration <= 0:
            raise ValueError("Calibration must be greater than zero")
        self.calibration = float(calibration)
        self.holidays = holidays or set()

    @staticmethod
    def calibration_factor(*, estimated: float, actual: float) -> float:
        if estimated <= 0 or actual < 0:
            raise ValueError("Estimated cost must be positive and actual cost non-negative")
        return actual / estimated

    @staticmethod
    def _day(timestamp: str, local_time: bool) -> str | None:
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            parsed = parsed.astimezone() if local_time else parsed.astimezone(UTC)
            return parsed.strftime("%Y-%m-%d")
        except (ValueError, TypeError, AttributeError):
            return None

    def scan_transcripts(
        self,
        since_iso_date: str | None = None,
        until_iso_date: str | None = None,
        *,
        local_time: bool = False,
    ) -> dict[str, Any]:
        totals: dict[str, Any] = {
            "total_cost_usd": 0.0,
            "total_tokens": 0,
            "tokens": {
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write_5m": 0,
                "cache_write_1h": 0,
            },
            "server_tools": {"web_search": 0, "web_fetch": 0},
            "by_day": {},
            "by_model": {},
            "provenance": {
                "kind": "local_transcript_estimate",
                "calibration": self.calibration,
                "timezone": "local" if local_time else "UTC",
                "price_cache": str(self.price_cache_path) if self.price_cache_path else None,
            },
        }
        if not self.projects_dir.exists():
            return totals

        seen_events: set[str] = set()
        for jsonl_file in sorted(self.projects_dir.glob("**/*.jsonl")):
            try:
                with open(jsonl_file, encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        stripped = line.strip()
                        if '"usage"' not in stripped:
                            continue
                        try:
                            entry = json.loads(stripped)
                        except ValueError:
                            continue
                        if entry.get("type") not in (None, "assistant"):
                            continue
                        message = entry.get("message") or entry
                        usage = message.get("usage") or {}
                        if not isinstance(usage, dict):
                            continue
                        event_id = (
                            entry.get("requestId")
                            or entry.get("id")
                            or message.get("id")
                            or entry.get("uuid")
                            or entry.get("event_id")
                            or hashlib.sha256(stripped.encode("utf-8")).hexdigest()
                        )
                        if event_id in seen_events:
                            continue
                        seen_events.add(str(event_id))

                        day = self._day(
                            entry.get("timestamp") or entry.get("created_at") or "", local_time
                        )
                        if (
                            day is None
                            or (since_iso_date and day < since_iso_date)
                            or (until_iso_date and day > until_iso_date)
                        ):
                            continue

                        input_tokens = int(usage.get("input_tokens") or 0)
                        output_tokens = int(usage.get("output_tokens") or 0)
                        cache_read = int(usage.get("cache_read_input_tokens") or 0)
                        creation = usage.get("cache_creation") or {}
                        cache_5m = int(creation.get("ephemeral_5m_input_tokens") or 0)
                        cache_1h = int(creation.get("ephemeral_1h_input_tokens") or 0)
                        if not cache_5m and not cache_1h:
                            cache_5m = int(usage.get("cache_creation_input_tokens") or 0)
                        server = usage.get("server_tool_use") or {}
                        searches = int(server.get("web_search_requests") or 0)
                        fetches = int(server.get("web_fetch_requests") or 0)
                        if not any(
                            (
                                input_tokens,
                                output_tokens,
                                cache_read,
                                cache_5m,
                                cache_1h,
                                searches,
                                fetches,
                            )
                        ):
                            continue

                        model = message.get("model") or "unknown"
                        input_price, output_price = PriceCatalog.get_price(
                            model, self.price_cache_path
                        )
                        raw_cost = (
                            (
                                input_tokens * input_price
                                + output_tokens * output_price
                                + cache_read * input_price * 0.1
                                + cache_5m * input_price * 1.25
                                + cache_1h * input_price * 2.0
                            )
                            / 1_000_000
                            + searches * WEB_SEARCH_USD
                            + fetches * WEB_FETCH_USD
                        )
                        cost = raw_cost * self.calibration

                        totals["total_cost_usd"] += cost
                        totals["by_day"][day] = totals["by_day"].get(day, 0.0) + cost
                        totals["by_model"][model] = totals["by_model"].get(model, 0.0) + cost
                        dimensions = {
                            "input": input_tokens,
                            "output": output_tokens,
                            "cache_read": cache_read,
                            "cache_write_5m": cache_5m,
                            "cache_write_1h": cache_1h,
                        }
                        for name, value in dimensions.items():
                            totals["tokens"][name] += value
                            totals["total_tokens"] += value
                        totals["server_tools"]["web_search"] += searches
                        totals["server_tools"]["web_fetch"] += fetches
            except OSError:
                continue
        return totals

    def get_summary_report(self, monthly_budget_usd: float) -> dict[str, Any]:
        now = datetime.now(UTC)
        first_of_month = now.strftime("%Y-%m-01")
        data = self.scan_transcripts(since_iso_date=first_of_month)
        month_cost = data["total_cost_usd"]
        ritmo = RitmoCalculator.calculate_pace(
            monthly_budget_usd, actual_spend_usd=month_cost, holidays=self.holidays
        )
        today_cost = data["by_day"].get(now.strftime("%Y-%m-%d"), 0.0)
        remaining_days = max(1, ritmo.days_remaining + 1)
        return {
            "estimate": True,
            "month_cost_usd": month_cost,
            "today_cost_usd": today_cost,
            "daily_budget_usd": (monthly_budget_usd - month_cost) / remaining_days,
            "monthly_budget_usd": monthly_budget_usd,
            "ritmo": ritmo,
            "by_day": data["by_day"],
            "by_model": data["by_model"],
            "tokens": data["tokens"],
            "server_tools": data["server_tools"],
            "provenance": data["provenance"],
            "price_cache_age_days": (
                PriceCatalog.cache_age_days(self.price_cache_path)
                if self.price_cache_path is not None
                else None
            ),
        }
