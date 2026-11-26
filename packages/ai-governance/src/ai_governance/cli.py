"""``ai-governance`` — the single entry point of the package."""

from __future__ import annotations

import argparse
import importlib
import sys

COMMANDS: dict[str, str] = {
    "install": "Install for the chosen agent(s): --scope user|project --agent <name>",
    "uninstall": "Remove exactly what was installed for the chosen agent(s)",
    "update": "Refresh project rules for the detected stacks (--all, --check, --dry-run)",
    "status": "What is installed where",
    "doctor": "Read-only health checks for user and project installs",
    "agents": "Capability matrix of the supported agents",
    "budget": "Fixed context (bytes/tokens) loaded per agent every session",
    "rules": "Browse the engineering-rules catalog (list, show, profiles)",
    "skills": "Keep each third-party skill in one place and copy it into agents (list, add, rm, sync, migrate)",
    "taskflow": "Task notebook and multi-provider design debates across agents",
    "brain": "Cross-agent second brain notes (add, search, show, list, edit, archive, import)",
    "jira": "Jira issues and transitions in Markdown",
    "confluence": "Confluence pages in Markdown",
    "pr-watch": "Read-only GitHub PR watcher (ready to merge, comments, CI failures, conflicts)",
    "slack-notify": "Send Markdown notifications to allowlisted Slack targets via a Bot Token",
    "config": "Show the effective configuration and where each value came from",
    "hook": "Agent hook entry point (used by installed hooks)",
    "ui": "Local visual dashboard for taskflow and second brain (start, stop, status, open)",
}
INSTALL_COMMANDS = (
    "install",
    "uninstall",
    "update",
    "status",
    "doctor",
    "agents",
    "budget",
)
_SUBCOMMAND_MODULES: dict[str, str] = {
    "rules": "ai_governance.rules.cli",
    "skills": "ai_governance.skills",
    "taskflow": "ai_governance.taskflow.cli",
    "brain": "ai_governance.brain.cli",
    "jira": "ai_governance.tools.jira",
    "confluence": "ai_governance.tools.confluence",
    "pr-watch": "ai_governance.tools.pr_watch",
    "slack-notify": "ai_governance.tools.slack_notify",
    "config": "ai_governance.config_cli",
    "hook": "ai_governance.hooks",
    "ui": "ai_governance.ui.cli",
}


def _build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="ai-governance",
        description="Per-agent engineering standards, token frugality and lightweight task tracking.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="subcommand")
    for name, help_text in COMMANDS.items():
        sub.add_parser(name, help=help_text, add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
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
    target = importlib.import_module(_SUBCOMMAND_MODULES[cmd])
    result = target.main(rest)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
