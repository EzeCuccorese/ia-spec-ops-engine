"""Read-only health checks for the user and project installs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .agents import HOOK_COMMAND_PREFIX
from .engine import END, START, Ledger, sha256
from .installer import PROJECT_DIR, ProjectConfig, global_ledger, installed_agents, sync_project

OK, WARN, FAIL = "OK", "WARN", "FAIL"
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


def _binary_rows() -> list[Row]:
    rows: list[Row] = []
    for binary in ("ai-governance", "ws"):
        found = shutil.which(binary)
        rows.append((f"binary:{binary}", OK if found else WARN, found or "not on PATH"))
    return rows


def _legacy_gemini_block() -> list[Row]:
    legacy = Path.home() / ".gemini" / "GEMINI.md"
    text = legacy.read_text(encoding="utf-8") if legacy.is_file() else ""
    if START not in text or END not in text:
        return []
    detail = (
        f"legacy ai-governance block in {legacy}; delete it "
        "(instructions now live in ~/.gemini/config/rules/ai-governance.md)"
    )
    return [("user:antigravity", WARN, detail)]


def _user_rows() -> list[Row]:
    user = global_ledger()
    agents = sorted(installed_agents(user))
    rows: list[Row] = [("user:agents", OK, ", ".join(agents) or "none installed")]
    rows.extend(_ledger_rows(user, "user"))
    if "antigravity" in agents:
        rows.extend(_legacy_gemini_block())
    return rows


def _claude_rows(root: Path) -> list[Row]:
    rows: list[Row] = [
        ("project:claude", FAIL, f"{name} exists; Claude ignores AGENTS.md")
        for name in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
        if (root / name).exists()
    ]
    user_hooks = _hook_commands(Path.home() / ".claude" / "settings.json")
    for name in ("settings.json", "settings.local.json"):
        duplicated = user_hooks & _hook_commands(root / ".claude" / name)
        if duplicated:
            detail = f"hooks also in .claude/{name} run twice: {sorted(duplicated)}"
            rows.append(("project:claude", WARN, detail))
    return rows


def _antigravity_rows(root: Path) -> list[Row]:
    rows: list[Row] = []
    if (root / ".agent").is_dir():
        rows.append(("project:antigravity", WARN, "legacy .agent/ folder; rules live in .agents/"))
    if (root / ".agents" / "settings.json").is_file():
        detail = ".agents/settings.json is no longer read; move it to .gemini/config.json"
        rows.append(("project:antigravity", WARN, detail))
    return rows


def _project_rows(root: Path) -> list[Row]:
    config = ProjectConfig.load(root)
    rows: list[Row] = [("project:agents", OK, ", ".join(config.agents))]
    rows.extend(_ledger_rows(Ledger(root / PROJECT_DIR / "lock.json", base=root), "project"))
    if "claude" in config.agents:
        rows.extend(_claude_rows(root))
    if "antigravity" in config.agents:
        rows.extend(_antigravity_rows(root))
    drifted = sync_project(root, dry_run=True).changed
    rows.append(
        ("project:drift", WARN, "out of date; run `ai-governance update`")
        if drifted
        else ("project:drift", OK, "up to date")
    )
    return rows


def check(root: Path | None) -> list[Row]:
    rows = _binary_rows() + _user_rows()
    if root is not None and (root / PROJECT_DIR / "config.toml").exists():
        rows.extend(_project_rows(root))
    return rows
