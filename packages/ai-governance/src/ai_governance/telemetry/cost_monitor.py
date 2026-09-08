"""
cost_monitor.py — Local transcript scanner & budget pacing analyzer.
Scans ~/.claude/projects/**/*.jsonl without external network calls, computing exact token usage and costs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .prices import PriceCatalog
from .ritmo import RitmoCalculator


class CostMonitor:
    def __init__(self, projects_dir: Path | None = None) -> None:
        self.projects_dir = projects_dir or (Path.home() / ".claude" / "projects")

    def scan_transcripts(
        self, since_iso_date: str | None = None, until_iso_date: str | None = None
    ) -> dict[str, Any]:
        """Scans JSONL transcripts and aggregates tokens and cost per day, deduplicating events."""
        totals = {
            "total_cost_usd": 0.0,
            "total_tokens": 0,
            "by_day": {},
            "by_model": {},
        }
        if not self.projects_dir.exists():
            return totals

        seen_events: set[str] = set()

        for jsonl_file in sorted(self.projects_dir.glob("**/*.jsonl")):
            try:
                with open(jsonl_file, encoding="utf-8") as f:
                    for line in f:
                        line_stripped = line.strip()
                        if not line_stripped:
                            continue
                        entry = json.loads(line_stripped)
                        msg = entry.get("message") or entry
                        usage = msg.get("usage") or {}
                        in_tok = usage.get("input_tokens", 0)
                        out_tok = usage.get("output_tokens", 0)
                        c_read = usage.get("cache_read_input_tokens", 0)
                        c_write = usage.get("cache_creation_input_tokens", 0)

                        if not (in_tok or out_tok or c_read or c_write):
                            continue

                        # Deduplication by event id, message id, uuid, or content hash
                        event_id = (
                            entry.get("id")
                            or (msg.get("id") if isinstance(msg, dict) else None)
                            or entry.get("uuid")
                            or entry.get("event_id")
                        )
                        if not event_id:
                            event_id = hashlib.sha256(line_stripped.encode("utf-8")).hexdigest()

                        if event_id in seen_events:
                            continue
                        seen_events.add(event_id)

                        model = msg.get("model", "claude-sonnet-4-6")
                        p_in, p_out = PriceCatalog.get_price(model)

                        # Cost in USD
                        cost = (
                            (in_tok / 1_000_000.0) * p_in
                            + (out_tok / 1_000_000.0) * p_out
                            + (c_read / 1_000_000.0) * (p_in * 0.1)
                            + (c_write / 1_000_000.0) * (p_in * 1.25)
                        )

                        ts_str = entry.get("timestamp") or entry.get("created_at") or ""
                        day = ts_str[:10] if ts_str else datetime.now().strftime("%Y-%m-%d")

                        if since_iso_date and day < since_iso_date:
                            continue
                        if until_iso_date and day > until_iso_date:
                            continue

                        totals["total_cost_usd"] += cost
                        totals["total_tokens"] += in_tok + out_tok + c_read + c_write
                        totals["by_day"].setdefault(day, 0.0)
                        totals["by_day"][day] += cost
                        totals["by_model"].setdefault(model, 0.0)
                        totals["by_model"][model] += cost
            except Exception:
                continue

        return totals

    def get_summary_report(self, monthly_budget_usd: float) -> dict[str, Any]:
        first_of_month = datetime.now().strftime("%Y-%m-01")
        data = self.scan_transcripts(since_iso_date=first_of_month)
        month_cost = data["total_cost_usd"]
        ritmo = RitmoCalculator.calculate_pace(monthly_budget_usd, actual_spend_usd=month_cost)

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_cost = data["by_day"].get(today_str, 0.0)

        return {
            "month_cost_usd": month_cost,
            "today_cost_usd": today_cost,
            "monthly_budget_usd": monthly_budget_usd,
            "ritmo": ritmo,
            "by_model": data["by_model"],
        }
