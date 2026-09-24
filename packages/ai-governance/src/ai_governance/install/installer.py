"""Install / update / uninstall orchestration for the user and project scopes.

- User scope: global artifacts of each *selected* agent; ledger in the state dir,
  which also registers every project installed on this machine (``update --all``).
- Project scope: rules for the detected stacks rendered into each selected agent's
  own folder, one shared ``AGENTS.md`` block, and ``.ai-governance/`` holding the
  committed config (``config.toml``) and ownership ledger (``lock.json``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from ..paths import state_dir
from ..rules.catalog import RuleCatalog
from . import content
from .agents import (
    AGENTS,
    RULES_DIR,
    BlockArtifact,
    FileArtifact,
    canonical_rule_path,
    render_canonical_rule,
    resolve_agents,
)
from .engine import Ledger, Owned, Report, sync

PROJECT_DIR = ".ai-governance"
CLAUDE_MEMORY_FILES = ("CLAUDE.md", ".claude/CLAUDE.md")


@dataclass
class ProjectConfig:
    agents: list[str] = field(default_factory=list)
    extra_rules: list[str] = field(default_factory=list)
    excluded_rules: list[str] = field(default_factory=list)
    gate: bool = True

    @classmethod
    def load(cls, root: Path) -> ProjectConfig:
        path = root / PROJECT_DIR / "config.toml"
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(
            agents=list(data.get("agents", [])),
            extra_rules=list(data.get("extra_rules", [])),
            excluded_rules=list(data.get("excluded_rules", [])),
            gate=bool(data.get("gate", True)),
        )

    def render(self) -> str:
        def arr(values: list[str]) -> str:
            return "[" + ", ".join(json.dumps(v) for v in values) + "]"

        return (
            "# ai-governance project config (commit this file).\n"
            "# Agents to render rules for; change with `ai-governance install|uninstall`.\n"
            f"agents = {arr(self.agents)}\n"
            "# Rule ids to force in or out regardless of stack detection.\n"
            f"extra_rules = {arr(self.extra_rules)}\n"
            f"excluded_rules = {arr(self.excluded_rules)}\n"
            "# Run `ws check --changed` when the agent ends a turn (Claude Code Stop hook).\n"
            f"gate = {'true' if self.gate else 'false'}\n"
        )


def detect_stacks(root: Path) -> set[str] | None:
    """Stacks via the ``ws detect --json`` contract; ``None`` when ws is unavailable."""
    ws = shutil.which("ws")
    if ws is None:
        return None
    try:
        proc = subprocess.run(
            [ws, "detect", "--dir", str(root), "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        data = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if proc.returncode != 0 or data.get("schema_version") != 1:
        return None
    return set(data.get("stacks", []))


def global_ledger() -> Ledger:
    return Ledger(state_dir() / "installed.json", base=None)


def _register_project(root: Path, *, present: bool, dry_run: bool) -> None:
    ledger = global_ledger()
    projects = set(ledger.extra.get("projects", []))
    key = str(root.resolve())
    if (key in projects) == present:
        return
    if present:
        projects.add(key)
    else:
        projects.discard(key)
    ledger.extra["projects"] = sorted(projects)
    ledger.save(Report(), dry_run)


def forget_project(root: Path, *, dry_run: bool = False) -> None:
    _register_project(root, present=False, dry_run=dry_run)


def registered_projects() -> list[Path]:
    return [Path(p) for p in global_ledger().extra.get("projects", [])]


# -- user scope --------------------------------------------------------------------


def install_user(agents: list[str], *, dry_run: bool = False, force: bool = False) -> Report:
    specs = resolve_agents(agents)
    ledger = global_ledger()
    desired = [Owned(spec.id, artifact) for spec in specs for artifact in spec.global_artifacts()]
    report = sync(
        desired, ledger, agents_in_scope={s.id for s in specs}, dry_run=dry_run, force=force
    )
    ledger.extra["package_version"] = __version__
    ledger.save(report, dry_run)
    return report


def uninstall_user(agents: list[str], *, dry_run: bool = False) -> Report:
    specs = resolve_agents(agents)
    ledger = global_ledger()
    report = sync([], ledger, agents_in_scope={s.id for s in specs}, dry_run=dry_run)
    ledger.save(report, dry_run)
    return report


# -- project scope -----------------------------------------------------------------


def _migrate_claude_memory(root: Path, report: Report, dry_run: bool) -> None:
    """Moves CLAUDE.md content into AGENTS.md (the only instructions file we support)."""
    agents_md = root / "AGENTS.md"
    for relative in CLAUDE_MEMORY_FILES:
        source = root / relative
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8").strip()
        if text and not dry_run:
            existing = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
            joined = f"{existing.rstrip()}\n\n{text}\n" if existing.strip() else f"{text}\n"
            agents_md.write_text(joined, encoding="utf-8")
        if not dry_run:
            source.unlink()
        report.add(f"migrated {relative} into", agents_md)
    if (root / "CLAUDE.local.md").exists():
        report.warnings.append(
            "CLAUDE.local.md still exists: while it does, Claude Code ignores AGENTS.md. "
            "Move its personal notes elsewhere and delete it."
        )


def _project_desired(root: Path, config: ProjectConfig, stacks: set[str]) -> list[Owned]:
    rules = RuleCatalog().select(
        stacks, extra=tuple(config.extra_rules), excluded=tuple(config.excluded_rules)
    )
    specs = resolve_agents(config.agents)
    desired = [
        Owned(spec.id, artifact)
        for spec in specs
        for artifact in spec.project_artifacts(root, rules, gate=config.gate)
    ]
    if specs:
        desired.extend(
            Owned(
                "project",
                FileArtifact(canonical_rule_path(root, rule), render_canonical_rule(rule)),
            )
            for rule in rules
        )
        body = content.PROJECT_BLOCK.format(rule_locations=f"`{RULES_DIR.as_posix()}/`")
        desired.append(Owned("project", BlockArtifact(root / "AGENTS.md", body)))
    return desired


def sync_project(
    root: Path,
    *,
    add_agents: list[str] = (),  # type: ignore[assignment]
    remove_agents: list[str] = (),  # type: ignore[assignment]
    dry_run: bool = False,
    force: bool = False,
) -> Report:
    """Install/update/uninstall for a project. With no agent changes this is ``update``."""
    root = root.resolve()
    config = ProjectConfig.load(root)
    resolve_agents([*add_agents, *remove_agents])
    before = set(config.agents)
    config.agents = [
        a for a in dict.fromkeys([*config.agents, *add_agents]) if a not in remove_agents
    ]
    if not config.agents and not before:
        raise ValueError("No agent selected. Pass --agent claude|codex|antigravity.")

    report = Report()
    stacks = detect_stacks(root)
    if stacks is None:
        report.warnings.append(
            "`ws` not found: stack detection skipped, only general rules selected. "
            "Install the workspace package and run `ai-governance update`."
        )
        stacks = set()
    if "claude" in config.agents:
        _migrate_claude_memory(root, report, dry_run)

    ledger = Ledger(root / PROJECT_DIR / "lock.json", base=root)
    scope = set(AGENTS) | {"project"}
    sync(
        _project_desired(root, config, stacks),
        ledger,
        agents_in_scope=scope,
        dry_run=dry_run,
        force=force,
        report=report,
    )

    config_path = root / PROJECT_DIR / "config.toml"
    if config.agents:
        ledger.extra.update(package_version=__version__, stacks=sorted(stacks))
        text = config.render()
        current = config_path.read_text(encoding="utf-8") if config_path.exists() else None
        if current != text:
            if not dry_run:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text(text, encoding="utf-8")
            report.add("updated" if current else "created", config_path)
        ledger.save(report, dry_run)
        _register_project(root, present=True, dry_run=dry_run)
    else:
        for path in (config_path, ledger.path):
            if path.exists():
                if not dry_run:
                    path.unlink()
                report.add("removed", path)
        if (
            not dry_run
            and (root / PROJECT_DIR).is_dir()
            and not any((root / PROJECT_DIR).iterdir())
        ):
            (root / PROJECT_DIR).rmdir()
        _register_project(root, present=False, dry_run=dry_run)
    return report
