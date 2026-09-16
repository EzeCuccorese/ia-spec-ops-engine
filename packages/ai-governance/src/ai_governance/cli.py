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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="governance",
        description="AI Governance — Engineering Standards, Token Frugality & Telemetry Engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand", help="Available Governance subcommands")

    # rules
    sub.add_parser("rules", help="Software Engineering Standards Catalog & Reversible Injector")

    # frugal
    sub.add_parser("frugal", help="Context Frugality & Tool Output Condenser")

    # statusline
    sub.add_parser("statusline", help="Real-time ANSI statusline for coding agents")

    # ritmo
    p_ritmo = sub.add_parser("ritmo", help="Business-day budget pacing calculator")
    p_ritmo.add_argument("--budget", type=float, default=100.0, help="Monthly budget in USD")
    p_ritmo.add_argument("--spent", type=float, default=0.0, help="Actual spend in USD")

    # usage
    p_usage = sub.add_parser("usage", help="Scan local Claude transcripts & monitor budget")
    p_usage.add_argument("--budget", type=float, default=100.0, help="Monthly budget in USD")

    # telemetry
    sub.add_parser("telemetry", help="Usage estimates, prices, pacing, and thresholds")

    # progress (with aliases task, progreso)
    sub.add_parser("progress", help="Lightweight cross-session task tracker (~300 tokens)")
    sub.add_parser("task", help=argparse.SUPPRESS)
    sub.add_parser("progreso", help=argparse.SUPPRESS)

    # jira
    sub.add_parser("jira", help="Jira ticket querying and transitions in Markdown")

    # confluence
    sub.add_parser("confluence", help="Confluence documentation reader and writer in Markdown")

    args_list = sys.argv[1:] if argv is None else list(argv)
    if not args_list:
        show_banner()
        parser.print_help()
        return 0

    cmd = args_list[0]
    remaining_args = args_list[1:]

    if cmd == "rules":
        from .rules.cli import main as rules_main

        sys.argv = ["rules"] + remaining_args
        return rules_main()
    elif cmd == "frugal":
        from .frugality.cli import main as frugal_main

        sys.argv = ["frugal"] + remaining_args
        return frugal_main()
    elif cmd == "statusline":
        from .telemetry.statusline import main as status_main

        sys.argv = ["statusline"] + remaining_args
        return status_main()
    elif cmd == "telemetry":
        from .telemetry.cli import main as telemetry_main

        return telemetry_main(remaining_args)
    elif cmd in ("ritmo", "usage"):
        from .telemetry.cli import main as telemetry_main

        return telemetry_main([cmd] + remaining_args)
    elif cmd in ("progress", "task", "progreso"):
        from .session.cli import main as session_main

        sys.argv = ["progress"] + remaining_args
        return session_main()
    elif cmd == "jira":
        from .tools.jira import main as jira_main

        sys.argv = ["jira"] + remaining_args
        jira_main()
        return 0
    elif cmd == "confluence":
        from .tools.confluence import main as confluence_main

        sys.argv = ["confluence"] + remaining_args
        confluence_main()
        return 0
    else:
        parser.parse_args()
        return 0


if __name__ == "__main__":
    sys.exit(main())
