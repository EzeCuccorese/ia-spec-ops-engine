"""Telemetry CLI: local Claude Code spend estimates, claude-usage pacing, prices and alerts."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

from ..output import emit_json, emit_kv, emit_status
from ..paths import state_dir
from .claude_usage import ClaudeUsageCalculator
from .cost_monitor import CostMonitor
from .prices import DEFAULT_FEED_URL, PriceCatalog
from .state import ThresholdTracker, UsageConfig, notify_macos


def runtime_dir() -> Path:
    return state_dir() / "telemetry"


def show_claude_usage_table(
    monthly_budget: float, actual_spend: float, holidays: set[date] | None = None
) -> None:
    status = ClaudeUsageCalculator.calculate_pace(
        monthly_budget, actual_spend_usd=actual_spend, holidays=holidays
    )
    pairs = [
        ("Monthly budget", f"${monthly_budget:.2f} USD"),
        ("Business days", f"{status.elapsed_business_days}/{status.total_business_days}"),
        ("Expected spend", f"${status.expected_spend_usd:.2f} USD"),
        ("Estimated local spend", f"${status.actual_spend_usd:.2f} USD"),
        ("Status", status.status_label),
    ]
    emit_kv(pairs, title="Claude usage vs. budget", full=True)


def show_usage_report(summary: dict) -> None:
    emit_status("warn", "Local transcript estimate; provider billing remains authoritative.")
    pairs = [
        ("Today", f"${summary['today_cost_usd']:.2f}"),
        ("Month", f"${summary['month_cost_usd']:.2f}"),
        ("Remaining workday allowance", f"${summary['daily_budget_usd']:.2f}"),
    ]
    cache_age = summary.get("price_cache_age_days")
    if cache_age is None:
        pairs.append(("Price cache", "not available; using bundled fallback"))
    elif cache_age > 30:
        pairs.append(
            ("Price cache", f"{cache_age} days old; run ai-governance telemetry prices update")
        )
    else:
        pairs.append(("Price cache", f"{cache_age} days old"))
    token_text = ", ".join(f"{name}={value}" for name, value in summary["tokens"].items())
    pairs.append(("Tokens", token_text))
    for model, cost in sorted(summary["by_model"].items(), key=lambda item: -item[1]):
        pairs.append((f"Model {model}", f"${cost:.2f}"))
    for label, key in (("Effort today", "effort_today"), ("Effort month", "effort_month")):
        text = format_effort(summary.get(key) or {})
        if text:
            pairs.append((label, text))
    emit_kv(pairs, title="Claude usage estimate", full=True)
    if summary.get("fast_calls"):
        emit_status("info", f"{summary['fast_calls']} fast-mode calls (billed at the fast rate).")


def format_effort(efforts: dict[str, dict[str, float]]) -> str:
    """Cost share per effort level; thinking share is diagnostic (already in output)."""
    total = sum(values["cost"] for values in efforts.values())
    if total <= 0:
        return ""
    parts = []
    for effort, values in sorted(efforts.items(), key=lambda item: -item[1]["cost"]):
        share = round(values["cost"] * 100 / total)
        thinking = ""
        if values["output"] and values["thinking"]:
            thinking = f", thinking {round(values['thinking'] * 100 / values['output'])}%"
        parts.append(f"{effort} ${values['cost']:.2f} ({share}%{thinking})")
    return " | ".join(parts)


GREEN, YELLOW, RED, BOLD, DIM, RESET = (
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[1m",
    "\033[2m",
    "\033[0m",
)


def _color(percent: float) -> str:
    if percent >= 90:
        return RED + BOLD
    return YELLOW if percent >= 50 else GREEN


def statusline_segment(base: Path, config: UsageConfig, *, today: date | None = None) -> str:
    """Today's spend vs. today's cap, the month's spend vs. the business-day pace,
    the month's spend vs. the monthly limit, and what is left of that limit.

    Today's cap is what the pace allows by the end of today minus what was spent
    before today, so savings from earlier days carry over and spending today does
    not move the cap.

    Reads the costs the Stop hook (`thresholds`) caches in state.json; rescans the
    transcripts only when that cache is from another day, since the status line
    renders on every turn.
    """
    current = today or date.today()
    state = ThresholdTracker.load(base / "state.json")
    if state.get("day") == current.isoformat():
        day_cost = float(state.get("last_day_cost") or 0)
        month_cost = float(state.get("last_month_cost") or 0)
    else:
        summary = _monitor(base, config).get_summary_report(config.effective_monthly_limit)
        day_cost, month_cost = summary["today_cost_usd"], summary["month_cost_usd"]
    limit = config.effective_monthly_limit
    pace = ClaudeUsageCalculator.calculate_pace(
        limit, actual_spend_usd=month_cost, target_date=current, holidays=config.holidays
    )
    expected = pace.expected_spend_usd
    day_cap = expected - (month_cost - day_cost)
    day_pct = _pct(day_cost, day_cap)
    pace_pct = _pct(month_cost, expected)
    limit_pct = _pct(month_cost, limit)
    sep = f" {DIM}·{RESET} "
    return sep.join(
        (
            f"{_color(day_pct)}today ${day_cost:.2f}/{day_cap:.0f} {day_pct:.0f}%{RESET}",
            f"{_color(pace_pct)}month ${month_cost:.0f}/{expected:.0f} {pace_pct:.0f}%{RESET}",
            f"{_color(limit_pct)}budget ${month_cost:.0f}/{limit:.0f} {limit_pct:.0f}%{RESET}",
            f"{_color(limit_pct)}left ${limit - month_cost:.0f}{RESET}",
        )
    )


def _pct(spent: float, cap: float) -> float:
    return spent / cap * 100 if cap > 0 else 100.0


def _monitor(base: Path, config: UsageConfig) -> CostMonitor:
    return CostMonitor(
        price_cache_path=base / "prices-cache.json",
        calibration=config.calibration,
        holidays=config.holidays,
    )


def _summary_json(summary: dict) -> dict:
    value = dict(summary)
    value["pace"] = asdict(value["pace"])
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance telemetry",
        description="Local Claude Code spend estimates (for plans whose UI hides running spend)",
    )
    sub = parser.add_subparsers(dest="cmd")
    usage = sub.add_parser(
        "claude-usage", help="Month-to-date Claude spend vs. business-day budget pace"
    )
    usage.add_argument("--budget", type=float, help="Monthly budget (default: config)")
    usage.add_argument("--spent", type=float, help="Override the scanned month spend")
    report = sub.add_parser("report", help="Today/month estimate by model and token type")
    report.add_argument("--budget", type=float)
    report.add_argument("--json", action="store_true")
    calibrate = sub.add_parser(
        "calibrate", help="Store the ratio between the real spend and the estimate for a period"
    )
    calibrate.add_argument("--from", dest="from_date", required=True)
    calibrate.add_argument("--to", dest="to_date", required=True)
    calibrate.add_argument("--actual", type=float, required=True)
    prices = sub.add_parser("prices", help="Manage the cached model price table")
    prices_sub = prices.add_subparsers(dest="prices_cmd")
    update = prices_sub.add_parser("update", help="Refresh the cached price table")
    update.add_argument("--url", default=DEFAULT_FEED_URL)
    sub.add_parser("statusline", help="Compact spend segment for the Claude Code status line")
    thresholds = sub.add_parser(
        "thresholds", help="Evaluate the daily/monthly alert thresholds (what the Stop hook runs)"
    )
    thresholds.add_argument("--notify", action="store_true")
    thresholds.add_argument("--json", action="store_true")
    return parser


def _claude_usage(args: argparse.Namespace, base: Path, config: UsageConfig) -> None:
    budget = args.budget or config.effective_monthly_limit
    spent = args.spent
    if spent is None:
        spent = _monitor(base, config).get_summary_report(budget)["month_cost_usd"]
    show_claude_usage_table(budget, spent, config.holidays)


def _report(args: argparse.Namespace, base: Path, config: UsageConfig) -> None:
    budget = args.budget or config.effective_monthly_limit
    summary = _monitor(base, config).get_summary_report(budget)
    if args.json:
        emit_json(_summary_json(summary))
    else:
        show_usage_report(summary)


def _calibrate(args: argparse.Namespace, base: Path, config: UsageConfig) -> None:
    raw_monitor = CostMonitor(price_cache_path=base / "prices-cache.json")
    estimate = raw_monitor.scan_transcripts(args.from_date, args.to_date)["total_cost_usd"]
    factor = CostMonitor.calibration_factor(estimated=estimate, actual=args.actual)
    replace(config, calibration=factor).save(base / "config.json")
    print(f"Calibration saved: {factor:.3f}")


def _prices(args: argparse.Namespace, base: Path, config: UsageConfig) -> None:
    if args.prices_cmd != "update":
        return
    document = PriceCatalog.refresh_cache(base / "prices-cache.json", args.url)
    print(f"Updated {len(document['prices'])} direct Anthropic model prices.")


def _statusline(args: argparse.Namespace, base: Path, config: UsageConfig) -> None:
    # The status line must never break a session.
    with contextlib.suppress(Exception):
        sys.stdout.write(statusline_segment(base, config))


def _thresholds(args: argparse.Namespace, base: Path, config: UsageConfig) -> None:
    summary = _monitor(base, config).get_summary_report(config.effective_monthly_limit)
    state_path = base / "state.json"
    messages, state = ThresholdTracker.evaluate(summary, config, ThresholdTracker.load(state_path))
    ThresholdTracker.save(state_path, state)
    if args.notify and config.notify_macos and messages:
        notify_macos("Claude usage estimate", " ".join(messages))
    if args.json:
        emit_json({"messages": messages, "state": state})
    elif messages:
        print("\n".join(messages))


COMMANDS = {
    "claude-usage": _claude_usage,
    "report": _report,
    "calibrate": _calibrate,
    "prices": _prices,
    "statusline": _statusline,
    "thresholds": _thresholds,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS.get(args.cmd)
    if handler is None:
        parser.print_help()
        return 0
    base = runtime_dir()
    try:
        handler(args, base, UsageConfig.load(base / "config.json"))
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        emit_status("error", f"Telemetry error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
