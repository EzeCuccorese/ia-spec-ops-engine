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

from .. import __version__, corporate
from ..paths import state_dir
from ..rules.catalog import RuleCatalog
from . import content
from .agents import (
    AGENTS,
    RULES_DIR,
    AgentSpec,
    BlockArtifact,
    FileArtifact,
    LinkArtifact,
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
    profiles: list[str] = field(default_factory=list)
    extra_rules: list[str] = field(default_factory=list)
    excluded_rules: list[str] = field(default_factory=list)
    gate: bool = True
    tables: str = ""

    @classmethod
    def load(cls, root: Path) -> ProjectConfig:
        path = root / PROJECT_DIR / "config.toml"
        if not path.exists():
            return cls()
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        tables = ""
        for i, line in enumerate(text.splitlines(keepends=True)):
            if line.startswith("["):
                tables = "".join(text.splitlines(keepends=True)[i:])
                break
        return cls(
            agents=list(data.get("agents", [])),
            profiles=list(data.get("profiles", [])),
            extra_rules=list(data.get("extra_rules", [])),
            excluded_rules=list(data.get("excluded_rules", [])),
            gate=bool(data.get("gate", True)),
            tables=tables,
        )

    def render(self) -> str:
        def arr(values: list[str]) -> str:
            return "[" + ", ".join(json.dumps(v) for v in values) + "]"

        text = (
            "# ai-governance project config (commit this file).\n"
            "# Agents to render rules for; change with `ai-governance install|uninstall`.\n"
            f"agents = {arr(self.agents)}\n"
            "# Opt-in rule groups (architecture, distributed, api); change with "
            "`ai-governance install|uninstall --profile`.\n"
            f"profiles = {arr(self.profiles)}\n"
            "# Rule ids to force in or out regardless of stack detection.\n"
            f"extra_rules = {arr(self.extra_rules)}\n"
            f"excluded_rules = {arr(self.excluded_rules)}\n"
            "# Run `ws check --changed` when the agent ends a turn (Claude Code Stop hook).\n"
            f"gate = {'true' if self.gate else 'false'}\n"
        )
        if self.tables:
            text += "\n" + self.tables
        return text


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


SCRIPTS_OWNER = "corporate"


def _corporate_rules(
    spec: AgentSpec, packs: list[corporate.CorporatePack], report: Report
) -> list[Owned]:
    """Every pack in the corporate folder, rendered for one agent; nothing to opt into."""
    desired: list[Owned] = []
    skipped: list[str] = []
    for pack in packs:
        rules = pack.rules()
        artifacts = spec.corporate_artifacts(rules)
        if rules and not artifacts:
            skipped.append(pack.name)
        desired.extend(Owned(spec.id, artifact) for artifact in artifacts)
    if skipped:
        report.warnings.append(
            f"{spec.name} has no per-file global rules: {', '.join(skipped)} rules skipped."
        )
    return desired


def _corporate_scripts(packs: list[corporate.CorporatePack], report: Report) -> list[Owned]:
    """One link per script name; on a clash the first pack (alphabetical) wins."""
    desired: list[Owned] = []
    owners: dict[str, str] = {}
    for pack in packs:
        for script in pack.scripts():
            if script.name in owners:
                report.warnings.append(
                    f"Script {script.name} of {pack.name} skipped: "
                    f"{owners[script.name]} already provides it."
                )
                continue
            owners[script.name] = pack.name
            link = LinkArtifact(corporate.bin_dir() / script.name, str(script))
            desired.append(Owned(SCRIPTS_OWNER, link))
    return desired


def _installed_agents(ledger: Ledger) -> set[str]:
    return {entry["agent"] for entry in ledger.entries} - {SCRIPTS_OWNER}


def install_user(agents: list[str], *, dry_run: bool = False, force: bool = False) -> Report:
    """Global artifacts of the agents plus every corporate pack present on disk.

    Pack rules are refreshed only for ``agents``; other installed agents keep theirs
    until they are installed again.
    """
    specs = resolve_agents(agents)
    ledger = global_ledger()
    packs = corporate.packs()
    report = Report()
    desired = [Owned(spec.id, artifact) for spec in specs for artifact in spec.global_artifacts()]
    for spec in specs:
        desired.extend(_corporate_rules(spec, packs, report))
    desired.extend(_corporate_scripts(packs, report))
    scope = {spec.id for spec in specs} | {SCRIPTS_OWNER}
    sync(desired, ledger, agents_in_scope=scope, dry_run=dry_run, force=force, report=report)
    ledger.extra["package_version"] = __version__
    ledger.save(report, dry_run)
    return report


def uninstall_user(agents: list[str], *, dry_run: bool = False) -> Report:
    """Removes the agents' artifacts; pack scripts go with the last installed agent."""
    scope = {spec.id for spec in resolve_agents(agents)}
    ledger = global_ledger()
    report = Report()
    keep_scripts = bool(_installed_agents(ledger) - scope)
    desired = _corporate_scripts(corporate.packs(), report) if keep_scripts else []
    sync(desired, ledger, agents_in_scope=scope | {SCRIPTS_OWNER}, dry_run=dry_run, report=report)
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


def _project_desired(
    root: Path, config: ProjectConfig, stacks: set[str], catalog: RuleCatalog
) -> list[Owned]:
    rules = catalog.select(
        stacks,
        profiles=tuple(config.profiles),
        extra=tuple(config.extra_rules),
        excluded=tuple(config.excluded_rules),
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


def _merged(
    current: list[str], add: tuple[str, ...] | list[str], remove: tuple[str, ...] | list[str]
) -> list[str]:
    return [value for value in dict.fromkeys([*current, *add]) if value not in remove]


Change = tuple[tuple[str, ...] | list[str], tuple[str, ...] | list[str]]


def _changed_config(config: ProjectConfig, *, agents: Change, profiles: Change) -> ProjectConfig:
    """Applies (add, remove) agent and profile changes; a project needs at least one agent."""
    resolve_agents([*agents[0], *agents[1]])
    had_agents = bool(config.agents)
    config.agents = _merged(config.agents, *agents)
    if not config.agents and not had_agents:
        raise ValueError("No agent selected. Pass --agent claude|codex|antigravity.")
    config.profiles = _merged(config.profiles, *profiles)
    return config


def _stacks_or_warn(root: Path, report: Report) -> set[str]:
    stacks = detect_stacks(root)
    if stacks is not None:
        return stacks
    report.warnings.append(
        "`ws` not found: stack detection skipped, only general rules selected. "
        "Install the workspace package and run `ai-governance update`."
    )
    return set()


def _prepare_project(
    root: Path, config: ProjectConfig, report: Report, *, dry_run: bool
) -> set[str]:
    """Detects the stacks and moves CLAUDE.md into AGENTS.md for Claude projects."""
    stacks = _stacks_or_warn(root, report)
    if "claude" in config.agents:
        _migrate_claude_memory(root, report, dry_run)
    return stacks


def _installed_rule_ids(ledger: Ledger) -> set[str]:
    prefix = f"{RULES_DIR.as_posix()}/"
    return {
        entry["path"].removeprefix(f"{prefix}ai-governance-").removesuffix(".md")
        for entry in ledger.entries
        if entry["kind"] == "file" and entry["path"].startswith(prefix)
    }


def _selected_rule_ids(catalog: RuleCatalog, config: ProjectConfig, stacks: set[str]) -> set[str]:
    rules = catalog.select(
        stacks,
        profiles=tuple(config.profiles),
        extra=tuple(config.extra_rules),
        excluded=tuple(config.excluded_rules),
    )
    return {rule.id for rule in rules}


def _warn_disabled_profiles(
    catalog: RuleCatalog, config: ProjectConfig, dropped: set[str], report: Report
) -> None:
    removed_by_profile: dict[str, list[str]] = {}
    for rule_id in sorted(dropped):
        rule = catalog.get(rule_id)
        if rule is None or rule.profile is None or rule.profile in config.profiles:
            continue
        removed_by_profile.setdefault(rule.profile, []).append(rule_id)
    for profile, ids in removed_by_profile.items():
        report.warnings.append(
            f'Rules of profile "{profile}" removed because it is not enabled: '
            f"{', '.join(ids)}. Enable with: ai-governance install --scope project "
            f"--profile {profile}"
        )


def _write_project_config(
    root: Path, config: ProjectConfig, report: Report, *, dry_run: bool
) -> None:
    config_path = root / PROJECT_DIR / "config.toml"
    text = config.render()
    current = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    if current == text:
        return
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(text, encoding="utf-8")
    report.add("updated" if current else "created", config_path)


def _remove_project_state(root: Path, ledger: Ledger, report: Report, *, dry_run: bool) -> None:
    for path in (root / PROJECT_DIR / "config.toml", ledger.path):
        if not path.exists():
            continue
        if not dry_run:
            path.unlink()
        report.add("removed", path)
    folder = root / PROJECT_DIR
    if not dry_run and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()


def sync_project(
    root: Path,
    *,
    add_agents: list[str] = (),  # type: ignore[assignment]
    remove_agents: list[str] = (),  # type: ignore[assignment]
    add_profiles: tuple[str, ...] = (),
    remove_profiles: tuple[str, ...] = (),
    dry_run: bool = False,
    force: bool = False,
) -> Report:
    """Install/update/uninstall for a project. With no agent changes this is ``update``."""
    root = root.resolve()
    catalog = RuleCatalog()
    catalog.check_profiles((*add_profiles, *remove_profiles))
    config = _changed_config(
        ProjectConfig.load(root),
        agents=(add_agents, remove_agents),
        profiles=(add_profiles, remove_profiles),
    )

    report = Report()
    stacks = _prepare_project(root, config, report, dry_run=dry_run)
    ledger = Ledger(root / PROJECT_DIR / "lock.json", base=root)
    installed_ids = _installed_rule_ids(ledger)
    sync(
        _project_desired(root, config, stacks, catalog),
        ledger,
        agents_in_scope=set(AGENTS) | {"project"},
        dry_run=dry_run,
        force=force,
        report=report,
    )
    dropped = installed_ids - _selected_rule_ids(catalog, config, stacks)
    _warn_disabled_profiles(catalog, config, dropped, report)

    if config.agents:
        ledger.extra.update(package_version=__version__, stacks=sorted(stacks))
        _write_project_config(root, config, report, dry_run=dry_run)
        ledger.save(report, dry_run)
    else:
        _remove_project_state(root, ledger, report, dry_run=dry_run)
    _register_project(root, present=bool(config.agents), dry_run=dry_run)
    return report
