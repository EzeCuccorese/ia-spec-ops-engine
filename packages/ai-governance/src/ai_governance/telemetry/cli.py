"""Telemetry CLI: local Claude Code spend estimates, claude-usage pacing, prices and alerts."""

from __future__ import annotations

import argparse
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
    emit_kv(pairs, title="Claude usage estimate", full=True)


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
    calibrate = sub.add_parser("calibrate")
    calibrate.add_argument("--from", dest="from_date", required=True)
    calibrate.add_argument("--to", dest="to_date", required=True)
    calibrate.add_argument("--actual", type=float, required=True)
    prices = sub.add_parser("prices")
    prices_sub = prices.add_subparsers(dest="prices_cmd")
    update = prices_sub.add_parser("update")
    update.add_argument("--url", default=DEFAULT_FEED_URL)
    thresholds = sub.add_parser("thresholds")
    thresholds.add_argument("--notify", action="store_true")
    thresholds.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    base = runtime_dir()
    config_path = base / "config.json"
    try:
        config = UsageConfig.load(config_path)
        if args.cmd == "claude-usage":
            budget = args.budget or config.effective_monthly_limit
            spent = args.spent
            if spent is None:
                spent = _monitor(base, config).get_summary_report(budget)["month_cost_usd"]
            show_claude_usage_table(budget, spent, config.holidays)
        elif args.cmd == "report":
            budget = args.budget or config.effective_monthly_limit
            summary = _monitor(base, config).get_summary_report(budget)
            if args.json:
                emit_json(_summary_json(summary))
            else:
                show_usage_report(summary)
        elif args.cmd == "calibrate":
            raw_monitor = CostMonitor(price_cache_path=base / "prices-cache.json")
            estimate = raw_monitor.scan_transcripts(args.from_date, args.to_date)["total_cost_usd"]
            factor = CostMonitor.calibration_factor(estimated=estimate, actual=args.actual)
            replace(config, calibration=factor).save(config_path)
            print(f"Calibration saved: {factor:.3f}")
        elif args.cmd == "prices" and args.prices_cmd == "update":
            document = PriceCatalog.refresh_cache(base / "prices-cache.json", args.url)
            print(f"Updated {len(document['prices'])} direct Anthropic model prices.")
        elif args.cmd == "thresholds":
            summary = _monitor(base, config).get_summary_report(config.effective_monthly_limit)
            state_path = base / "state.json"
            messages, state = ThresholdTracker.evaluate(
                summary, config, ThresholdTracker.load(state_path)
            )
            ThresholdTracker.save(state_path, state)
            if args.notify and config.notify_macos and messages:
                notify_macos("Claude usage estimate", " ".join(messages))
            if args.json:
                emit_json({"messages": messages, "state": state})
            elif messages:
                print("\n".join(messages))
        else:
            parser.print_help()
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        emit_status("error", f"Telemetry error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
