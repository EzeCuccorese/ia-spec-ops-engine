"""CLI for local usage estimates, pacing, price maintenance, and notifications."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .cost_monitor import CostMonitor
from .prices import DEFAULT_FEED_URL, PriceCatalog
from .ritmo import RitmoCalculator
from .state import TelemetryConfig, ThresholdTracker, notify_macos
from .statusline import format_statusline

console = Console()


def runtime_dir() -> Path:
    return Path(
        os.environ.get("SPECOPS_USAGE_DIR")
        or os.environ.get("CLAUDE_USAGE_DIR")
        or Path.home() / ".specops" / "usage-monitor"
    )


def show_ritmo_table(monthly_budget: float, actual_spend: float) -> None:
    status = RitmoCalculator.calculate_pace(monthly_budget, actual_spend_usd=actual_spend)
    table = Table(title="Budget ritmo", border_style="cyan")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Monthly budget", f"${monthly_budget:.2f} USD")
    table.add_row("Business days", f"{status.elapsed_business_days}/{status.total_business_days}")
    table.add_row("Expected spend", f"${status.expected_spend_usd:.2f} USD")
    table.add_row("Estimated local spend", f"${status.actual_spend_usd:.2f} USD")
    table.add_row("Status", status.status_label)
    console.print(table)


def show_usage_report(summary: dict) -> None:
    console.print(
        "[yellow]Local transcript estimate; provider billing remains authoritative.[/yellow]"
    )
    table = Table(title="Claude usage estimate", border_style="cyan")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Today", f"${summary['today_cost_usd']:.2f}")
    table.add_row("Month", f"${summary['month_cost_usd']:.2f}")
    table.add_row("Remaining workday allowance", f"${summary['daily_budget_usd']:.2f}")
    cache_age = summary.get("price_cache_age_days")
    if cache_age is None:
        table.add_row("Price cache", "not available; using bundled fallback")
    elif cache_age > 30:
        table.add_row("Price cache", f"{cache_age} days old; run telemetry prices update")
    else:
        table.add_row("Price cache", f"{cache_age} days old")
    token_text = ", ".join(f"{name}={value}" for name, value in summary["tokens"].items())
    table.add_row("Tokens", token_text)
    for model, cost in sorted(summary["by_model"].items(), key=lambda item: -item[1]):
        table.add_row(f"Model {model}", f"${cost:.2f}")
    console.print(table)


def _monitor(base: Path, config: TelemetryConfig) -> CostMonitor:
    return CostMonitor(
        price_cache_path=base / "prices-cache.json",
        calibration=config.calibration,
        holidays=config.holidays,
    )


def _summary_json(summary: dict) -> dict:
    value = dict(summary)
    value["ritmo"] = asdict(value["ritmo"])
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telemetry", description="SpecOps local telemetry")
    sub = parser.add_subparsers(dest="cmd")
    ritmo = sub.add_parser("ritmo")
    ritmo.add_argument("--budget", type=float, default=100.0)
    ritmo.add_argument("--spent", type=float, default=0.0)
    statusline = sub.add_parser("statusline")
    statusline.add_argument("--ritmo", action="store_true")
    statusline.add_argument("--budget", type=float, default=100.0)
    statusline.add_argument("--context-warning", type=float, default=60.0)
    for name in ("usage", "report"):
        report = sub.add_parser(name)
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
        config = TelemetryConfig.load(config_path)
        if args.cmd == "ritmo":
            show_ritmo_table(args.budget, args.spent)
        elif args.cmd == "statusline":
            payload = json.loads(sys.stdin.read() or "{}")
            output = format_statusline(
                payload,
                include_ritmo=args.ritmo,
                monthly_budget=args.budget,
                context_warning_pct=args.context_warning,
            )
            if output:
                print(output)
        elif args.cmd in ("usage", "report"):
            budget = args.budget or config.effective_monthly_limit
            summary = _monitor(base, config).get_summary_report(budget)
            if args.json:
                print(json.dumps(_summary_json(summary), indent=2))
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
                print(json.dumps({"messages": messages, "state": state}, indent=2))
            elif messages:
                console.print("\n".join(messages))
        else:
            parser.print_help()
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        console.print(f"[red]Telemetry error: {exc}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
