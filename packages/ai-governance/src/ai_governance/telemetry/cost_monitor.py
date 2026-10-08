"""Local Claude transcript cost estimator with explicit provenance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .claude_usage import ClaudeUsageCalculator
from .prices import PriceCatalog

WEB_SEARCH_USD = 10.0 / 1000.0
WEB_FETCH_USD = 10.0 / 1000.0

TOKEN_DIMENSIONS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def _int(mapping: dict[str, Any], key: str) -> int:
    return int(mapping.get(key) or 0)


@dataclass(frozen=True)
class _Usage:
    input: int
    output: int
    cache_read: int
    cache_write_5m: int
    cache_write_1h: int
    searches: int
    fetches: int
    thinking: int
    fast: bool

    @classmethod
    def parse(cls, usage: dict[str, Any]) -> _Usage:
        creation = usage.get("cache_creation") or {}
        write_5m = _int(creation, "ephemeral_5m_input_tokens")
        write_1h = _int(creation, "ephemeral_1h_input_tokens")
        if not write_5m and not write_1h:
            write_5m = _int(usage, "cache_creation_input_tokens")
        server = usage.get("server_tool_use") or {}
        return cls(
            input=_int(usage, "input_tokens"),
            output=_int(usage, "output_tokens"),
            cache_read=_int(usage, "cache_read_input_tokens"),
            cache_write_5m=write_5m,
            cache_write_1h=write_1h,
            searches=_int(server, "web_search_requests"),
            fetches=_int(server, "web_fetch_requests"),
            thinking=_int(usage.get("output_tokens_details") or {}, "thinking_tokens"),
            fast=usage.get("speed") == "fast",
        )

    def dimensions(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in TOKEN_DIMENSIONS}

    def is_empty(self) -> bool:
        return not any((*self.dimensions().values(), self.searches, self.fetches))


@dataclass(frozen=True)
class _Event:
    day: str
    model: str
    effort: str
    usage: _Usage
    cost: float


def _file_lines(path: Path) -> Iterator[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            yield from handle
    except OSError:
        return


def _transcript_lines(projects_dir: Path) -> Iterator[str]:
    for jsonl_file in sorted(projects_dir.glob("**/*.jsonl")):
        yield from _file_lines(jsonl_file)


def _parse_line(line: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """(entry, message, usage) of an assistant transcript line that carries usage."""
    if '"usage"' not in line:
        return None
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("type") not in (None, "assistant"):
        return None
    message = entry.get("message") or entry
    usage = message.get("usage") or {}
    return (entry, message, usage) if isinstance(usage, dict) else None


def _event_id(entry: dict[str, Any], message: dict[str, Any], line: str) -> str:
    return str(
        entry.get("requestId")
        or entry.get("id")
        or message.get("id")
        or entry.get("uuid")
        or entry.get("event_id")
        or hashlib.sha256(line.encode("utf-8")).hexdigest()
    )


def _timestamp(entry: dict[str, Any]) -> str:
    return str(entry.get("timestamp") or entry.get("created_at") or "")


def _effort(entry: dict[str, Any]) -> str:
    return str(entry.get("perTurnEffort") or entry.get("effort") or "unknown")


def _in_window(day: str | None, since: str | None, until: str | None) -> bool:
    if day is None:
        return False
    return not ((since and day < since) or (until and day > until))


def _accumulate(totals: dict[str, Any], event: _Event) -> None:
    usage = event.usage
    totals["total_cost_usd"] += event.cost
    totals["by_day"][event.day] = totals["by_day"].get(event.day, 0.0) + event.cost
    totals["by_model"][event.model] = totals["by_model"].get(event.model, 0.0) + event.cost
    bucket = (
        totals["by_effort"]
        .setdefault(event.day, {})
        .setdefault(event.effort, {"cost": 0.0, "output": 0, "thinking": 0})
    )
    bucket["cost"] += event.cost
    bucket["output"] += usage.output
    bucket["thinking"] += usage.thinking
    totals["fast_calls"] += int(usage.fast)
    for name, value in usage.dimensions().items():
        totals["tokens"][name] += value
        totals["total_tokens"] += value
    totals["server_tools"]["web_search"] += usage.searches
    totals["server_tools"]["web_fetch"] += usage.fetches


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
        totals = self._new_totals(local_time)
        if not self.projects_dir.exists():
            return totals
        window = (since_iso_date, until_iso_date, local_time)
        seen_events: set[str] = set()
        for line in _transcript_lines(self.projects_dir):
            event = self._event(line.strip(), seen_events, window)
            if event is not None:
                _accumulate(totals, event)
        return totals

    def _new_totals(self, local_time: bool) -> dict[str, Any]:
        return {
            "total_cost_usd": 0.0,
            "total_tokens": 0,
            "tokens": dict.fromkeys(TOKEN_DIMENSIONS, 0),
            "server_tools": {"web_search": 0, "web_fetch": 0},
            "by_day": {},
            "by_model": {},
            # day -> effort -> {cost, output, thinking}. Diagnostic only: thinking tokens
            # are already billed inside output_tokens.
            "by_effort": {},
            # usage.speed == "fast": billed at the fast-mode multiplier (see prices.Rates).
            "fast_calls": 0,
            "provenance": {
                "kind": "local_transcript_estimate",
                "calibration": self.calibration,
                "timezone": "local" if local_time else "UTC",
                "price_cache": str(self.price_cache_path) if self.price_cache_path else None,
            },
        }

    def _event(
        self, line: str, seen_events: set[str], window: tuple[str | None, str | None, bool]
    ) -> _Event | None:
        """One billable assistant event, or None (not usage, duplicate, outside the window)."""
        parsed = _parse_line(line)
        if parsed is None:
            return None
        entry, message, usage = parsed
        event_id = _event_id(entry, message, line)
        if event_id in seen_events:
            return None
        seen_events.add(event_id)
        day = self._day(_timestamp(entry), window[2])
        tokens = _Usage.parse(usage)
        if not _in_window(day, window[0], window[1]) or tokens.is_empty():
            return None
        model = message.get("model") or "unknown"
        return _Event(str(day), model, _effort(entry), tokens, self._cost(model, tokens))

    def _cost(self, model: str, tokens: _Usage) -> float:
        prompt = tokens.input + tokens.cache_read + tokens.cache_write_5m + tokens.cache_write_1h
        rates = PriceCatalog.rates(
            model, self.price_cache_path, prompt_tokens=prompt, fast=tokens.fast
        )
        per_million = (
            tokens.input * rates.input
            + tokens.output * rates.output
            + tokens.cache_read * rates.cache_read
            + tokens.cache_write_5m * rates.cache_write_5m
            + tokens.cache_write_1h * rates.cache_write_1h
        )
        server = tokens.searches * WEB_SEARCH_USD + tokens.fetches * WEB_FETCH_USD
        return (per_million / 1_000_000 + server) * self.calibration

    @staticmethod
    def merge_effort(
        by_effort: dict[str, dict[str, dict[str, float]]], include: Callable[[str], bool]
    ) -> dict[str, dict[str, float]]:
        merged: dict[str, dict[str, float]] = {}
        for day, efforts in by_effort.items():
            if not include(day):
                continue
            for effort, values in efforts.items():
                target = merged.setdefault(effort, {"cost": 0.0, "output": 0, "thinking": 0})
                for key, value in values.items():
                    target[key] += value
        return merged

    def get_summary_report(self, monthly_budget_usd: float) -> dict[str, Any]:
        now = datetime.now(UTC)
        first_of_month = now.strftime("%Y-%m-01")
        data = self.scan_transcripts(since_iso_date=first_of_month)
        month_cost = data["total_cost_usd"]
        pace = ClaudeUsageCalculator.calculate_pace(
            monthly_budget_usd, actual_spend_usd=month_cost, holidays=self.holidays
        )
        today_cost = data["by_day"].get(now.strftime("%Y-%m-%d"), 0.0)
        remaining_days = max(1, pace.days_remaining + 1)
        month = now.strftime("%Y-%m")
        today = now.strftime("%Y-%m-%d")
        return {
            "estimate": True,
            "month_cost_usd": month_cost,
            "today_cost_usd": today_cost,
            "daily_budget_usd": (monthly_budget_usd - month_cost) / remaining_days,
            "monthly_budget_usd": monthly_budget_usd,
            "pace": pace,
            "by_day": data["by_day"],
            "by_model": data["by_model"],
            "effort_today": self.merge_effort(data["by_effort"], lambda d: d == today),
            "effort_month": self.merge_effort(data["by_effort"], lambda d: d.startswith(month)),
            "fast_calls": data["fast_calls"],
            "tokens": data["tokens"],
            "server_tools": data["server_tools"],
            "provenance": data["provenance"],
            "price_cache_age_days": (
                PriceCatalog.cache_age_days(self.price_cache_path)
                if self.price_cache_path is not None
                else None
            ),
        }
