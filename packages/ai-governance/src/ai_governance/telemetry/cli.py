"""
cli.py — Entrypoint for `telemetry`, `statusline`, and `ritmo` pacing.
"""

from __future__ import annotations

import argparse
import json
import sys
from rich.console import Console
from rich.table import Table

from .cost_monitor import CostMonitor
from .ritmo import RitmoCalculator
from .statusline import format_statusline

console = Console()


def show_ritmo_table(monthly_budget: float, actual_spend: float) -> None:
    st = RitmoCalculator.calculate_pace(monthly_budget, actual_spend_usd=actual_spend)
    table = Table(title="⏱️ Budget Ritmo (Pacing by Business Days)", border_style="cyan")
    table.add_column("Metric", style="bold green")
    table.add_column("Value", style="yellow")

    table.add_row("Monthly Budget", f"${monthly_budget:.2f} USD")
    table.add_row("Business Days", f"{st.elapsed_business_days} / {st.total_business_days} days ({st.pace_ratio*100:.1f}%)")
    table.add_row("Expected Spend to Date", f"${st.expected_spend_usd:.2f} USD")
    table.add_row("Actual Spend to Date", f"${st.actual_spend_usd:.2f} USD")
    diff_style = "[green]" if st.is_under_budget else "[red]"
    table.add_row("Variance", f"{diff_style}{st.variance_usd:+.2f} USD[/]")
    table.add_row("Pacing Status", f"{diff_style}{st.status_label}[/]")
    console.print(table)


def main() -> int:
    parser = argparse.ArgumentParser(prog="telemetry", description="SpecOps AI Telemetry & Ritmo Pacing")
    sub = parser.add_subparsers(dest="cmd")

    p_ritmo = sub.add_parser("ritmo", help="Calculate business-day pacing")
    p_ritmo.add_argument("--budget", type=float, default=100.0, help="Monthly budget in USD")
    p_ritmo.add_argument("--spent", type=float, default=0.0, help="Actual spend in USD")

    p_status = sub.add_parser("statusline", help="Format Claude Code statusline from stdin")
    p_status.add_argument("--ritmo", action="store_true", help="Include ritmo pace in statusline")
    p_status.add_argument("--budget", type=float, default=100.0, help="Monthly budget for ritmo")

    p_usage = sub.add_parser("usage", help="Scan local Claude transcripts")
    p_usage.add_argument("--budget", type=float, default=100.0, help="Monthly budget in USD")

    args = parser.parse_args()

    if args.cmd == "ritmo":
        show_ritmo_table(args.budget, args.spent)
        return 0
    elif args.cmd == "statusline":
        try:
            raw = sys.stdin.read()
            if not raw.strip():
                return 0
            payload = json.loads(raw)
            out = format_statusline(payload, include_ritmo=args.ritmo, monthly_budget=args.budget)
            if out:
                print(out)
        except Exception:
            pass
        return 0
    elif args.cmd == "usage":
        monitor = CostMonitor()
        summary = monitor.get_summary_report(args.budget)
        show_ritmo_table(args.budget, summary["month_cost_usd"])
        return 0
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
