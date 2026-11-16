"""Third-party skills: each one lives in exactly one directory and is linked into the agents.

A skill is a directory holding ``SKILL.md`` plus optional scripts and files. The single real
copy lives in the personal store (``<personal root>/skills/<name>/``) or in a company pack
(``<pack>/skills/<name>/``). Agents see it through a directory symlink, never a copy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import corporate
from .output import emit_rows, emit_status, emit_text
from .personal import personal_skills_dir

if TYPE_CHECKING:
    from .install.agents import AgentSpec

SKILL_FILE = "SKILL.md"
IGNORED_ENTRIES = frozenset({"synced"})
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
PERSONAL_LAYER = "personal"


class SkillError(Exception):
    """A skill operation that cannot proceed; the message says why."""


@dataclass(frozen=True)
class SkillSource:
    name: str
    layer: str
    path: Path


def bundled_names() -> frozenset[str]:
    from .install import content

    return frozenset(content.SKILLS)


def _is_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / SKILL_FILE).is_file()


def _skill_dirs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if not p.name.startswith(".") and _is_skill_dir(p))


def _selected_packs(pack_names: Sequence[str] | None) -> list[corporate.CorporatePack]:
    if not corporate.corporate_root().is_dir():
        return []
    try:
        return corporate.packs(only=pack_names)
    except ValueError as exc:
        raise SkillError(str(exc)) from exc


def _declared_sources(root: Path | None, pack_names: Sequence[str] | None) -> list[SkillSource]:
    found = [
        SkillSource(path.name, PERSONAL_LAYER, path.resolve())
        for path in _skill_dirs(personal_skills_dir(root))
    ]
    for pack in _selected_packs(pack_names):
        found.extend(
            SkillSource(p.name, f"company:{pack.name}", p.resolve()) for p in pack.skills()
        )
    return found


def collect(root: Path | None = None, pack_names: Sequence[str] | None = None) -> list[SkillSource]:
    """Every skill source, with unique names across bundled, company and personal layers."""
    bundled = bundled_names()
    seen: dict[str, SkillSource] = {}
    for source in _declared_sources(root, pack_names):
        if source.name in bundled:
            raise SkillError(
                f"Skill '{source.name}' at {source.path} collides with the bundled skill of the same name"
            )
        if source.name in seen:
            other = seen[source.name]
            raise SkillError(
                f"Skill '{source.name}' is provided twice: {other.path} ({other.layer}) and "
                f"{source.path} ({source.layer})"
            )
        seen[source.name] = source
    return list(seen.values())


def _check_name(name: str) -> str:
    if not NAME_PATTERN.fullmatch(name):
        raise SkillError(f"Invalid skill name '{name}': use letters, digits, '.', '_' and '-'")
    return name


def _sync_and_emit() -> None:
    from .install.installer import skill_agents, sync_skill_links

    if not skill_agents():
        emit_status(
            "warn", "No agent installed: run `ai-governance install --scope user --agent <a>`."
        )
        return
    emit_text("\n".join(sync_skill_links().lines()), full=True)


# -- list ----------------------------------------------------------------------------


def _link_state(folder: Path, source: SkillSource) -> str:
    entry = folder / source.name
    if entry.is_symlink() and os.readlink(entry) == str(source.path):
        return "linked"
    return "foreign" if entry.exists() or entry.is_symlink() else "missing"


def _agent_states(specs: list[AgentSpec], source: SkillSource) -> str:
    parts = []
    for spec in specs:
        folder = spec.skills_dir()
        if folder is not None:
            parts.append(f"{spec.id}={_link_state(folder, source)}")
    return ", ".join(parts) or "no agent installed"


def _foreign_entries(specs: list[AgentSpec], known: set[str]) -> list[tuple[str, str, str, str]]:
    rows = []
    for spec in specs:
        folder = spec.skills_dir()
        if folder is None or not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.name.startswith(".") or entry.name in IGNORED_ENTRIES | known:
                continue
            rows.append((entry.name, "foreign", str(entry), spec.id))
    return rows


def list_skills() -> int:
    from .install.installer import skill_agents

    sources = collect()
    specs = skill_agents()
    rows = [(s.name, s.layer, str(s.path), _agent_states(specs, s)) for s in sources]
    known = {s.name for s in sources} | bundled_names()
    rows.extend(_foreign_entries(specs, known))
    if not rows:
        emit_status("info", f"No skills found in {personal_skills_dir()}")
        return 0
    emit_rows(rows, headers=("Skill", "Source", "Path", "Agents"), full=True)
    return 0


# -- add / rm / sync -----------------------------------------------------------------


def add_skill(source_dir: Path, name: str | None = None) -> int:
    if not _is_skill_dir(source_dir):
        raise SkillError(f"{source_dir} is not a skill directory: no {SKILL_FILE} inside")
    skill_name = _check_name(name or source_dir.resolve().name)
    existing = {s.name: s for s in collect()}
    if skill_name in existing or skill_name in bundled_names():
        raise SkillError(f"Skill '{skill_name}' already exists; remove it first or pick --name")
    destination = personal_skills_dir() / skill_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, destination, symlinks=True)
    emit_status(
        "ok",
        f"Copied into the personal store: {destination}. The store is now the single source "
        f"of truth; {source_dir} is left untouched and no longer used.",
    )
    _sync_and_emit()
    return 0


def remove_skill(name: str) -> int:
    _check_name(name)
    destination = personal_skills_dir() / name
    if not (destination.is_symlink() or destination.exists()):
        owner = next((s for s in collect() if s.name == name), None)
        where = f" (it comes from {owner.layer}: {owner.path})" if owner else ""
        raise SkillError(
            f"Personal skill '{name}' not found{where}; only personal skills can be removed"
        )
    if destination.is_symlink():
        destination.unlink()
    else:
        shutil.rmtree(destination)
    emit_status("ok", f"Removed personal skill '{name}'.")
    _sync_and_emit()
    return 0


def sync_skills() -> int:
    _sync_and_emit()
    return 0


# -- migrate -------------------------------------------------------------------------


def _home_skill_dirs() -> list[Path]:
    home = Path.home()
    return [
        home / ".claude" / "skills",
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".gemini" / "config" / "skills",
    ]


def _tree_digest(root: Path) -> str:
    """Content fingerprint of a directory: relative names, file bytes and link targets."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode())
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _entry_key(entry: Path) -> tuple[str, str]:
    """Identity of a directory entry without following the entry itself (only its parent)."""
    return (str(entry.parent.resolve()), entry.name)


def _locations(name: str) -> list[Path]:
    seen: set[tuple[str, str]] = set()
    found: list[Path] = []
    for folder in _home_skill_dirs():
        entry = folder / name
        if (entry.is_symlink() or entry.exists()) and _entry_key(entry) not in seen:
            seen.add(_entry_key(entry))
            found.append(entry)
    return found


def _candidate_names(sources: list[SkillSource]) -> list[str]:
    skip = IGNORED_ENTRIES | bundled_names()
    linked = {(s.name, s.path) for s in sources}
    names: set[str] = set()
    for folder in _home_skill_dirs():
        for entry in folder.iterdir() if folder.is_dir() else []:
            adopted = (entry.name, Path(os.path.realpath(entry))) in linked
            if not entry.name.startswith(".") and entry.name not in skip and not adopted:
                names.add(entry.name)
    return sorted(names)


@dataclass(frozen=True)
class MigrationPlan:
    name: str
    locations: list[Path]
    chosen: Path
    destination: Path


def _real_copies(locations: list[Path]) -> dict[Path, str]:
    copies: dict[Path, str] = {}
    for entry in locations:
        real = Path(os.path.realpath(entry))
        if _is_skill_dir(real) and real not in copies:
            copies[real] = _tree_digest(real)
    return copies


def _choose_copy(name: str, copies: dict[Path, str], picked: Path | None) -> Path:
    if not copies:
        raise SkillError(f"'{name}': no real copy with a {SKILL_FILE} found (dangling links only)")
    if picked is not None:
        chosen = Path(os.path.realpath(picked))
        if chosen not in copies:
            raise SkillError(f"'{name}': --from {picked} is not one of: {_paths(copies)}")
        return chosen
    if len(set(copies.values())) > 1:
        raise SkillError(
            f"'{name}': copies differ, nothing done. Pick one with --from <path>: {_paths(copies)}"
        )
    return next(iter(copies))


def _paths(copies: dict[Path, str]) -> str:
    return ", ".join(str(path) for path in copies)


def _destination(name: str, pack: str | None) -> Path:
    if pack is None:
        return personal_skills_dir() / name
    if pack not in corporate.available():
        raise SkillError(
            f"Unknown corporate pack '{pack}'. Available: {', '.join(corporate.available()) or '(none)'}"
        )
    return corporate.corporate_root() / pack / "skills" / name


def _plan(
    name: str, sources: list[SkillSource], pack: str | None, picked: Path | None
) -> MigrationPlan:
    _check_name(name)
    provider = next((s for s in sources if s.name == name), None)
    if provider is not None:
        raise SkillError(f"'{name}' is already provided by {provider.layer}: {provider.path}")
    locations = _locations(name)
    if not locations:
        raise SkillError(f"'{name}': not found in any agent skills directory")
    chosen = _choose_copy(name, _real_copies(locations), picked)
    destination = _destination(name, pack)
    if destination.exists() or destination.is_symlink():
        raise SkillError(f"'{name}': {destination} already exists")
    return MigrationPlan(name, locations, chosen, destination)


def _plan_lines(plan: MigrationPlan, prefix: str) -> list[str]:
    from .install.installer import skill_agents

    lines = [f"{prefix}move {plan.chosen} -> {plan.destination}"]
    lines.extend(f"{prefix}delete {entry}" for entry in plan.locations if entry != plan.chosen)
    for spec in skill_agents():
        folder = spec.skills_dir()
        if folder is not None:
            lines.append(f"{prefix}link {folder / plan.name} -> {plan.destination.resolve()}")
    return lines


def _execute(plan: MigrationPlan) -> None:
    plan.destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(plan.chosen), str(plan.destination))
    for entry in plan.locations:
        if entry.is_symlink():
            entry.unlink()
        elif entry.exists():
            shutil.rmtree(entry)


@dataclass(frozen=True)
class MigrateOptions:
    names: Sequence[str] = ()
    dry_run: bool = False
    pack: str | None = None
    picked: Path | None = None


def _migration_names(options: MigrateOptions, sources: list[SkillSource]) -> list[str]:
    if options.picked is not None and len(options.names) != 1:
        raise SkillError("--from needs exactly one skill name")
    return list(options.names) or _candidate_names(sources)


def migrate_skills(options: MigrateOptions) -> int:
    sources = collect()
    prefix = "[dry-run] " if options.dry_run else ""
    failures = 0
    migrated = False
    for name in _migration_names(options, sources):
        try:
            plan = _plan(name, sources, options.pack, options.picked)
        except SkillError as exc:
            emit_status("error", str(exc))
            failures += 1
            continue
        emit_text("\n".join(_plan_lines(plan, prefix)), full=True)
        if not options.dry_run:
            _execute(plan)
            migrated = True
    if migrated:
        _sync_and_emit()
    return 1 if failures else 0


# -- CLI -----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance skills",
        description="Keep each skill in one directory and link it into the installed agents.",
    )
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="Skills, their source and per-agent link state")
    add_p = sub.add_parser("add", help="Copy a skill directory into the personal store and link it")
    add_p.add_argument("directory", type=Path, help="Directory holding SKILL.md")
    add_p.add_argument("--name", help="Skill name (default: the directory name)")
    rm_p = sub.add_parser("rm", help="Remove a personal skill and its links")
    rm_p.add_argument("name", help="Personal skill name")
    sub.add_parser("sync", help="Reconcile the links for every skill source")
    mig_p = sub.add_parser("migrate", help="Adopt skills already present in agent directories")
    mig_p.add_argument("names", nargs="*", help="Skill names (default: every unmanaged one)")
    mig_p.add_argument("--dry-run", action="store_true", help="Print the plan, change nothing")
    mig_p.add_argument("--pack", help="Move into this company pack instead of the personal store")
    mig_p.add_argument(
        "--from", dest="picked", type=Path, help="Which copy to keep when copies differ"
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.action == "list":
        return list_skills()
    if args.action == "add":
        return add_skill(args.directory, args.name)
    if args.action == "rm":
        return remove_skill(args.name)
    if args.action == "sync":
        return sync_skills()
    return migrate_skills(MigrateOptions(args.names, args.dry_run, args.pack, args.picked))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.action:
        parser.print_help()
        return 0
    try:
        return _run(args)
    except (SkillError, OSError) as exc:
        emit_status("error", str(exc))
        return 1
