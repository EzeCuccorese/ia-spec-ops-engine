"""Master CLI for AI Governance tools."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel

console = Console()


def show_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🛡️  AI GOVERNANCE[/bold cyan]\n"
            "[white]Autonomous Standards, Context Frugality, Token Optimization & Telemetry[/white]",
            border_style="cyan",
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="governance",
        description="AI Governance — Engineering Standards, Token Frugality & Telemetry Engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand", help="Available Governance subcommands")

    sub.add_parser("rules", help="Software Engineering Standards Catalog & Reversible Injector")
    sub.add_parser("frugal", help="Context Frugality & Tool Output Condenser")
    sub.add_parser("statusline", help="Real-time ANSI statusline for coding agents")
    sub.add_parser("telemetry", help="Usage estimates, prices, pacing, and thresholds")
    sub.add_parser("progress", help="Lightweight cross-session task tracker (~300 tokens)")
    sub.add_parser("jira", help="Jira ticket querying and transitions in Markdown")
    sub.add_parser("confluence", help="Confluence documentation reader and writer in Markdown")

    # Note: "ritmo"/"usage" (telemetry aliases) and "task" (progress alias) are
    # dispatched directly in main() below and intentionally omitted here so
    # they stay out of --help output while remaining functional.

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()

    args_list = sys.argv[1:] if argv is None else list(argv)
    if not args_list:
        show_banner()
        parser.print_help()
        return 0

    cmd = args_list[0]
    remaining_args = args_list[1:]

    if cmd == "rules":
        from .rules.cli import main as rules_main

        rules_main(remaining_args)
        return 0
    elif cmd == "frugal":
        from .frugality.cli import main as frugal_main

        return frugal_main(remaining_args)
    elif cmd == "statusline":
        from .telemetry.statusline import main as status_main

        return status_main()
    elif cmd == "telemetry":
        from .telemetry.cli import main as telemetry_main

        return telemetry_main(remaining_args)
    elif cmd in ("ritmo", "usage"):
        from .telemetry.cli import main as telemetry_main

        return telemetry_main([cmd] + remaining_args)
    elif cmd in ("progress", "task"):
        from .session.cli import main as session_main

        return session_main(remaining_args)
    elif cmd == "jira":
        from .tools.jira import main as jira_main

        jira_main(remaining_args)
        return 0
    elif cmd == "confluence":
        from .tools.confluence import main as confluence_main

        confluence_main(remaining_args)
        return 0
    else:
        parser.parse_args(args_list)
        return 0


if __name__ == "__main__":
    sys.exit(main())
