"""Read-only doctor for `governance doctor`.

Checks that deterministic tools are on PATH, that the detected host's config
wires the automatic triggers to the right commands, and that AGENTS.md carries
the rules and harness blocks. Never writes anything.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from ..output import emit_json, emit_status, emit_text
from ..rules.core.catalog import RuleCatalog, ToolDefinition
from ..rules.core.hosts import HostBinding, bindings_for, detect_host
from ..rules.core.injector import (
    END_MARKER,
    HARNESS_END_MARKER,
    HARNESS_START_MARKER,
    START_MARKER,
)

Status = str  # "OK" | "MISSING" | "WARN" | "N/A"
Check = tuple[Status, str, str]


def _tool_presence_checks(catalog: RuleCatalog) -> list[Check]:
    seen: dict[str, str] = {}  # token -> package
    for tool in catalog.tools:
        token = tool.command.split()[0]
        seen.setdefault(token, tool.package)

    checks: list[Check] = []
    for token, package in seen.items():
        hint = f"uv pip install -e packages/{package}"
        status = "OK" if shutil.which(token) else "MISSING"
        checks.append((status, token, hint))
    return checks


def _hook_commands(settings: dict[str, Any], event: str, matcher: str | None = None) -> list[str]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    entries = hooks.get(event)
    if not isinstance(entries, list):
        return []
    commands: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if matcher is not None:
            entry_matcher = entry.get("matcher")
            if entry_matcher not in (None, "", matcher):
                continue
        hook_list = entry.get("hooks")
        if not isinstance(hook_list, list):
            continue
        for hook in hook_list:
            if isinstance(hook, dict):
                command = hook.get("command")
                if isinstance(command, str):
                    commands.append(command)
    return commands


def _binding_satisfied(settings: dict[str, Any], tool: ToolDefinition, trigger: str) -> bool:
    if trigger == "before-shell-command":
        commands = _hook_commands(settings, "PreToolUse", matcher="Bash")
    elif trigger == "after-shell-command":
        commands = _hook_commands(settings, "PostToolUse", matcher="Bash")
    elif trigger == "on-turn-end":
        commands = _hook_commands(settings, "Stop")
    elif trigger == "on-worktree-create":
        commands = _hook_commands(settings, "WorktreeCreate")
    else:
        return False
    return any(tool.command in command for command in commands)


def _host_wiring_checks(catalog: RuleCatalog, host: str | None) -> list[Check]:
    if host is None:
        return [("N/A", "host", "no supported host detected")]

    bindings: dict[str, HostBinding] = {b.trigger: b for b in bindings_for(host)}
    settings_path = Path.home() / ".claude" / "settings.json"

    settings: dict[str, Any] | None = None
    parse_failed = False
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            settings = loaded if isinstance(loaded, dict) else {}
            if not isinstance(loaded, dict):
                parse_failed = True
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            parse_failed = True

    checks: list[Check] = []
    for tool in catalog.automatic_tools():
        binding = bindings.get(tool.trigger)
        if binding is None:
            continue
        name = f"host:{tool.trigger}"
        if settings is None and not parse_failed:
            checks.append(("MISSING", name, binding.location))
        elif parse_failed:
            checks.append(("WARN", name, binding.location))
        else:
            assert settings is not None
            satisfied = _binding_satisfied(settings, tool, tool.trigger)
            checks.append(("OK" if satisfied else "MISSING", name, binding.location))
    return checks


def _agents_md_checks(target: Path) -> list[Check]:
    if not target.exists():
        return [
            ("MISSING", "agents.md:rules", "governance rules install"),
            ("MISSING", "agents.md:harness", "governance harness install"),
        ]
    content = target.read_text(encoding="utf-8")
    rules_ok = START_MARKER in content and END_MARKER in content
    harness_ok = HARNESS_START_MARKER in content and HARNESS_END_MARKER in content
    return [
        ("OK" if rules_ok else "MISSING", "agents.md:rules", "governance rules install"),
        ("OK" if harness_ok else "MISSING", "agents.md:harness", "governance harness install"),
    ]


def _runtime_dir_check() -> Check:
    base = os.environ.get("SPECOPS_USAGE_DIR") or str(Path.home() / ".specops" / "usage-monitor")
    path = Path(base)
    name = "runtime-dir"
    if not path.exists():
        return ("WARN", name, f"{path} does not exist yet (created on first use)")
    if os.access(path, os.W_OK):
        return ("OK", name, str(path))
    return ("WARN", name, f"{path} is not writable")


def _target_agents_md(root: Path, is_global: bool) -> Path:
    from ..rules.agents import AgentsRulesAdapter

    return AgentsRulesAdapter().get_target_file(root, is_global)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doctor",
        description="Read-only check of tools, host wiring and AGENTS.md blocks",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--global", dest="is_global", action="store_true")
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--host", dest="host", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))

    try:
        catalog = RuleCatalog()
        host = args.host or detect_host()
        target = _target_agents_md(args.root, args.is_global)

        checks: list[Check] = []
        checks.extend(_tool_presence_checks(catalog))
        checks.extend(_host_wiring_checks(catalog, host))
        checks.extend(_agents_md_checks(target))
        checks.append(_runtime_dir_check())

        ok = sum(1 for status, _, _ in checks if status == "OK")
        missing = sum(1 for status, _, _ in checks if status == "MISSING")
        warn = sum(1 for status, _, _ in checks if status == "WARN")

        if args.as_json:
            emit_json(
                {
                    "host": host,
                    "checks": [
                        {"status": status, "name": name, "hint": hint}
                        for status, name, hint in checks
                    ],
                    "ok": ok,
                    "missing": missing,
                    "warn": warn,
                }
            )
        else:
            # Hints only matter when something needs fixing; keep OK lines short.
            lines = [
                f"{status:<7} {name}" if status == "OK" else f"{status:<7} {name} — {hint}"
                for status, name, hint in checks
            ]
            lines.append(f"summary: {ok} ok, {missing} missing, {warn} warn")
            emit_text("\n".join(lines), full=True)

        return 1 if missing else 0
    except Exception as exc:  # pragma: no cover - defensive top-level boundary
        emit_status("error", str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
