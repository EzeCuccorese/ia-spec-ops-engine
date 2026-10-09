"""``ai-governance`` — the single entry point of the package."""

from __future__ import annotations

import argparse
import sys

COMMANDS: dict[str, str] = {
    "install": "Install for the chosen agent(s): --scope user|project --agent <name>",
    "uninstall": "Remove exactly what was installed for the chosen agent(s)",
    "update": "Refresh project rules for the detected stacks (--all, --check, --dry-run)",
    "status": "What is installed where",
    "doctor": "Read-only health checks for user and project installs",
    "agents": "Capability matrix of the supported agents",
    "budget": "Fixed context (bytes/tokens) loaded per agent every session",
    "probe": "Verify on this machine what an agent loads and which hooks fire",
    "rules": "Browse the engineering-rules catalog (list, show, profiles)",
    "progress": "Compact cross-session task tracker",
    "telemetry": "Claude spend estimates (claude-usage), prices and threshold alerts",
    "jira": "Jira issues and transitions in Markdown",
    "confluence": "Confluence pages in Markdown",
    "completion": "Print the zsh <TAB> completion of ai-governance, ws or spec",
    "hook": "Agent hook entry point (used by installed hooks)",
}
INSTALL_COMMANDS = (
    "install",
    "uninstall",
    "update",
    "status",
    "doctor",
    "agents",
    "budget",
    "probe",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance",
        description="Per-agent engineering standards, token frugality, telemetry and progress.",
    )
    sub = parser.add_subparsers(dest="subcommand")
    for name, help_text in COMMANDS.items():
        sub.add_parser(name, help=help_text, add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["probe-record"] and len(args) == 3:
        from .install.probe import record

        return record(args[1], args[2])
    if not args or args[0] not in COMMANDS:
        parser = _build_parser()
        if args and args[0] not in ("-h", "--help"):
            parser.parse_args(args)
        parser.print_help()
        return 0
    cmd, rest = args[0], args[1:]
    if cmd in INSTALL_COMMANDS:
        from .install.cli import main as install_main

        return install_main(cmd, rest)
    if cmd == "rules":
        from .rules.cli import main as rules_main

        return rules_main(rest)
    if cmd == "progress":
        from .session.cli import main as session_main

        return session_main(rest)
    if cmd == "telemetry":
        from .telemetry.cli import main as telemetry_main

        return telemetry_main(rest)
    if cmd == "jira":
        from .tools.jira import main as jira_main

        jira_main(rest)
        return 0
    if cmd == "confluence":
        from .tools.confluence import main as confluence_main

        confluence_main(rest)
        return 0
    if cmd == "completion":
        from .completion import main as completion_main

        return completion_main(rest)
    from .hooks import main as hook_main

    return hook_main(rest)


if __name__ == "__main__":
    sys.exit(main())
