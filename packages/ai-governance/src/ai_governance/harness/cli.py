"""CLI for `governance harness` — deterministic tools index and self-wiring."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..output import emit_json, emit_rows, emit_status, emit_text
from ..rules.agents import AgentsRulesAdapter
from ..rules.core.catalog import RuleCatalog
from ..rules.core.hosts import HOST_TRIGGER_MAP
from ..rules.core.injector import HARNESS_END_MARKER, HARNESS_START_MARKER, BlockInjector
from .render import render_wiring_block


def _rendered_block(catalog: RuleCatalog) -> str:
    return render_wiring_block(catalog.tools, HOST_TRIGGER_MAP)


def _list_tools(catalog: RuleCatalog, *, full: bool, as_json: bool) -> int:
    tools = catalog.tools
    if as_json:
        emit_json(
            [
                {
                    "id": t.id,
                    "trigger": t.trigger,
                    "command": t.command,
                    "purpose": t.purpose,
                }
                for t in tools
            ]
        )
        return 0
    rows = [(t.id, t.trigger, t.command, t.purpose) for t in tools]
    emit_rows(
        rows,
        headers=("ID", "Trigger", "Command", "Purpose"),
        title="Harness Tools",
        full=full,
        more_hint="harness list --full",
    )
    return 0


def _install(root: Path, is_global: bool) -> int:
    catalog = RuleCatalog()
    target = AgentsRulesAdapter().get_target_file(root, is_global)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        content = target.read_text(encoding="utf-8") if target.exists() else ""
        block = _rendered_block(catalog)
        new_content = BlockInjector.inject(
            content, block, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER
        )
        target.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        emit_status("error", f"Failed to write harness wiring: {exc}")
        return 1
    emit_status("ok", f"Harness wiring written: {target}")
    return 0


def _uninstall(root: Path, is_global: bool) -> int:
    target = AgentsRulesAdapter().get_target_file(root, is_global)
    if not target.exists():
        emit_status("ok", f"Nothing to uninstall: {target} does not exist")
        return 0
    try:
        content = target.read_text(encoding="utf-8")
        new_content = BlockInjector.remove(
            content, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER
        )
        if not new_content.strip():
            target.unlink()
        else:
            target.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        emit_status("error", f"Failed to remove harness wiring: {exc}")
        return 1
    emit_status("ok", f"Harness wiring removed: {target}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Deterministic tools index and self-wiring block for AGENTS.md",
    )
    sub = parser.add_subparsers(dest="action")

    list_parser = sub.add_parser("list", help="List catalog tools")
    list_parser.add_argument("--full", action="store_true", help="Disable output truncation")
    list_parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON")

    install_parser = sub.add_parser("install", help="Inject the wiring block into AGENTS.md")
    install_parser.add_argument("--global", dest="is_global", action="store_true")
    install_parser.add_argument("--local", dest="is_local", action="store_true")
    install_parser.add_argument("--root", type=Path, default=Path.cwd())

    uninstall_parser = sub.add_parser("uninstall", help="Remove the wiring block from AGENTS.md")
    uninstall_parser.add_argument("--global", dest="is_global", action="store_true")
    uninstall_parser.add_argument("--local", dest="is_local", action="store_true")
    uninstall_parser.add_argument("--root", type=Path, default=Path.cwd())

    sub.add_parser("show", help="Print the rendered wiring block without writing")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))

    try:
        if args.action == "list":
            return _list_tools(RuleCatalog(), full=args.full, as_json=args.as_json)
        if args.action == "install":
            return _install(args.root, args.is_global)
        if args.action == "uninstall":
            return _uninstall(args.root, args.is_global)
        if args.action == "show":
            emit_text(_rendered_block(RuleCatalog()), full=True)
            return 0
        parser.print_help()
        return 0
    except Exception as exc:  # pragma: no cover - defensive top-level boundary
        emit_status("error", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
