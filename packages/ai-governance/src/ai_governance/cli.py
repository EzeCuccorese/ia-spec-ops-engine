"""
cli.py — Master CLI for SpecOps AI Governance.
Unifies rules, frugality, telemetry, ritmo, and session management.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel

console = Console()


def show_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🛡️  SPECOPS AI GOVERNANCE[/bold cyan]\n"
            "[white]Autonomous Standards, Context Frugality, Token Optimization & Telemetry[/white]",
            border_style="cyan",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="governance",
        description="SpecOps AI Governance — Engineering Standards, Token Frugality & Telemetry Engine.",
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

    # config
    sub.add_parser(
        "config",
        help="Initialize and manage SpecOps workspace configuration (.specops/config.json)",
    )

    # agent
    sub.add_parser(
        "agent",
        help="Manage universal AGENTS.md coding agent adapter",
    )

    # doctor
    sub.add_parser("doctor", help="Run environment and system diagnostics")

    # audit
    sub.add_parser("audit", help="Audit repository against governance checkpoints")

    args_list = sys.argv[1:] if argv is None else list(argv)
    if not args_list:
        show_banner()
        parser.print_help()
        return 0

    cmd = args_list[0]
    remaining_args = args_list[1:]

    if cmd == "config":
        try:
            from workspace_engine.config.init_config import run_config_init
        except ImportError:
            console.print(
                "[bold yellow]Notice:[/bold yellow] 'workspace_engine' is not installed or available.\n"
                "Install sibling package 'ia-spec-ops-workspace' to use 'governance config'."
            )
            return 1

        cfg_args = remaining_args
        if cfg_args and cfg_args[0] == "init":
            cfg_args = cfg_args[1:]
        return run_config_init(cfg_args)
    elif cmd == "agent":
        try:
            from spec.cli import main as spec_main
        except ImportError:
            console.print(
                "[bold yellow]Notice:[/bold yellow] 'spec' is not installed or available.\n"
                "Install sibling package 'spec' to use 'governance agent'."
            )
            return 1

        try:
            spec_main(["agent"] + remaining_args)
            return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
    elif cmd == "doctor":
        try:
            from spec.cli import main as spec_main
            from workspace_engine.cli.main import doctor_check
        except ImportError:
            console.print(
                "[bold yellow]Notice:[/bold yellow] 'spec' or 'ia-spec-ops-workspace' is not installed or available.\n"
                "Install sibling packages ('spec', 'ia-spec-ops-workspace') to use 'governance doctor'."
            )
            return 1

        is_json = "--json" in remaining_args
        if not is_json:
            doctor_check()
            print()
        try:
            spec_main(["doctor"] + remaining_args)
            return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
    elif cmd == "audit":
        try:
            from spec.cli import main as spec_main
        except ImportError:
            console.print(
                "[bold yellow]Notice:[/bold yellow] 'spec' is not installed or available.\n"
                "Install sibling package 'spec' to use 'governance audit'."
            )
            return 1

        try:
            spec_main(["audit"] + remaining_args)
            return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
    elif cmd == "rules":
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
