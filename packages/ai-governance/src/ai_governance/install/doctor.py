"""Read-only health checks for the user and project installs."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .agents import HOOK_COMMAND_PREFIX
from .engine import Ledger, sha256
from .installer import PROJECT_DIR, ProjectConfig, global_ledger, sync_project

OK, WARN, FAIL = "OK", "WARN", "FAIL"
# Providers where Claude Code does not support AGENTS.md yet (changelog v2.1.277).
CLAUDE_UNSUPPORTED_PROVIDERS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
Row = tuple[str, str, str]


def _ledger_rows(ledger: Ledger, scope: str) -> list[Row]:
    rows: list[Row] = []
    for entry in ledger.entries:
        path = ledger.resolve(entry["path"])
        label = f"{scope}:{entry['agent']}"
        if not path.exists():
            rows.append((label, FAIL, f"missing {path}"))
        elif (
            entry["kind"] == "file" and sha256(path.read_text(encoding="utf-8")) != entry["sha256"]
        ):
            rows.append((label, WARN, f"edited locally {path}"))
    return rows


def _hook_commands(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {
        hook.get("command", "")
        for groups in data.get("hooks", {}).values()
        for group in groups
        for hook in group.get("hooks", [])
        if str(hook.get("command", "")).startswith(HOOK_COMMAND_PREFIX)
    }


def check(root: Path | None) -> list[Row]:
    rows: list[Row] = []
    for binary in ("ai-governance", "ws"):
        found = shutil.which(binary)
        rows.append((f"binary:{binary}", OK if found else WARN, found or "not on PATH"))

    user = global_ledger()
    agents = sorted({entry["agent"] for entry in user.entries})
    rows.append(("user:agents", OK, ", ".join(agents) or "none installed"))
    rows.extend(_ledger_rows(user, "user"))

    if root is None or not (root / PROJECT_DIR / "config.toml").exists():
        return rows
    config = ProjectConfig.load(root)
    rows.append(("project:agents", OK, ", ".join(config.agents)))
    rows.extend(_ledger_rows(Ledger(root / PROJECT_DIR / "lock.json", base=root), "project"))

    if "claude" in config.agents:
        for name in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
            if (root / name).exists():
                rows.append(("project:claude", FAIL, f"{name} exists; Claude ignores AGENTS.md"))
        user_hooks = _hook_commands(Path.home() / ".claude" / "settings.json")
        for name in ("settings.json", "settings.local.json"):
            duplicated = user_hooks & _hook_commands(root / ".claude" / name)
            if duplicated:
                rows.append(
                    (
                        "project:claude",
                        WARN,
                        f"hooks also in .claude/{name} run twice: {sorted(duplicated)}",
                    )
                )
    if "antigravity" in config.agents:
        if (root / ".agent").is_dir():
            rows.append(
                ("project:antigravity", WARN, "legacy .agent/ folder; rules live in .agents/")
            )
        if (root / ".agents" / "settings.json").is_file():
            rows.append(
                (
                    "project:antigravity",
                    WARN,
                    ".agents/settings.json is no longer read; move it to .gemini/config.json",
                )
            )
    if "claude" in config.agents:
        providers = [name for name in CLAUDE_UNSUPPORTED_PROVIDERS if os.environ.get(name)]
        if providers:
            rows.append(
                (
                    "project:claude",
                    WARN,
                    f"{', '.join(providers)} set: Claude Code does not read AGENTS.md on this "
                    "provider; the project block will not load",
                )
            )

    drift = sync_project(root, dry_run=True)
    if drift.changed:
        rows.append(("project:drift", WARN, "out of date; run `ai-governance update`"))
    else:
        rows.append(("project:drift", OK, "up to date"))
    return rows
