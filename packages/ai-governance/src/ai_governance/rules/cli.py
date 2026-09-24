"""``ai-governance rules`` — browse the bundled engineering-rules catalog."""

from __future__ import annotations

import argparse

from ..output import emit_rows, emit_status, emit_text
from .catalog import RuleCatalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-governance rules")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list", help="List catalog rules with their stacks (details: show <id>)")
    show = sub.add_parser("show", help="Print one rule")
    show.add_argument("rule_id")
    args = parser.parse_args(argv)
    catalog = RuleCatalog()
    if args.cmd == "show":
        rule = catalog.get(args.rule_id)
        if rule is None:
            emit_status("error", f"Unknown rule: {args.rule_id}")
            return 1
        emit_text(rule.content, full=True)
        return 0
    rows = [
        (rule.id, ",".join(rule.stacks) or "general")
        for rule in sorted(catalog.rules, key=lambda r: r.id)
    ]
    emit_rows(rows, headers=("Rule", "Stacks"), full=True)
    return 0
