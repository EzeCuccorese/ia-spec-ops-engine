"""Deterministic, reversible application of artifacts with an ownership ledger.

Every file, block or hook entry written is recorded (path + sha256) so that:
- re-running is a no-op when nothing changed;
- files edited locally since the last run are kept and reported, never clobbered;
- files that existed before and were not written by us are never overwritten;
- uninstall removes exactly what was written.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agents import (
    MARKER,
    Artifact,
    BlockArtifact,
    DirArtifact,
    FileArtifact,
    HookEntry,
    HooksArtifact,
    LinkArtifact,
)
from .blocks import BlockInjector

LEDGER_SCHEMA = 1
START = f"<!-- {MARKER}:start -->"
END = f"<!-- {MARKER}:end -->"
logger = logging.getLogger(__name__)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_digest(root: Path) -> str:
    """Content fingerprint of a directory: relative paths, executable bits, bytes and link targets."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"L" + os.readlink(path).encode("utf-8"))
        elif path.is_file():
            mode_tag = b"X" if path.stat().st_mode & 0o111 else b"F"
            digest.update(mode_tag + path.read_bytes())
        else:
            digest.update(b"D")
    return digest.hexdigest()


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_symlink():
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, mode)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return
    path.write_text(text, encoding="utf-8")


@dataclass
class Report:
    changes: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, action: str, path: Path | str) -> None:
        self.changes.append((action, str(path)))

    @property
    def changed(self) -> bool:
        return any(action != "unchanged" for action, _ in self.changes)

    def lines(self) -> list[str]:
        """One line per change; 3+ same-action changes in one folder collapse to a count."""
        groups: dict[tuple[str, str], list[str]] = {}
        for action, path in self.changes:
            if action != "unchanged":
                groups.setdefault((action, str(Path(path).parent)), []).append(path)
        out: list[str] = []
        for (action, folder), paths in groups.items():
            if len(paths) >= 3:
                out.append(f"{action}: {len(paths)} files in {folder}/")
            else:
                out.extend(f"{action}: {path}" for path in paths)
        out.extend(f"WARN: {warning}" for warning in self.warnings)
        return out or ["No changes."]


@dataclass(frozen=True)
class Owned:
    """An artifact paired with the agent that owns it (``project`` = shared)."""

    agent: str
    artifact: Artifact


class Ledger:
    """JSON ownership record. Project paths are stored relative to the root."""

    def __init__(self, path: Path, base: Path | None) -> None:
        self.path = path
        self.base = base
        data = json.loads(_read(path) or "{}")
        self.entries: list[dict[str, Any]] = list(data.get("entries", []))
        self.extra: dict[str, Any] = {
            key: value for key, value in data.items() if key not in ("entries", "schema_version")
        }

    def key(self, path: Path) -> str:
        """Resolves the parent only: a link is keyed by its own path, never by its target."""
        if self.base is not None:
            try:
                full = self.resolve(str(path))
                resolved = full.parent.resolve() / full.name
                return resolved.relative_to(self.base.resolve()).as_posix()
            except ValueError as exc:
                logger.debug("Path %s is outside ledger base %s: %s", path, self.base, exc)
        return str(path)

    def resolve(self, key: str) -> Path:
        candidate = Path(key)
        if self.base is not None and not candidate.is_absolute():
            return self.base / candidate
        return candidate

    def find(self, kind: str, path: Path) -> dict[str, Any] | None:
        key = self.key(path)
        return next((e for e in self.entries if e["kind"] == kind and e["path"] == key), None)

    def save(self, report: Report, dry_run: bool) -> None:
        payload = {"schema_version": LEDGER_SCHEMA, **self.extra, "entries": self.entries}
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if _read(self.path) != text:
            if not dry_run:
                _write(self.path, text)
            report.add("updated", self.path)


# -- hooks JSON ------------------------------------------------------------------


def _merge_hooks(
    data: dict[str, Any], entries: tuple[HookEntry, ...], name: str | None = None
) -> None:
    hooks = data.setdefault(name or "hooks", {})
    for entry in entries:
        groups = hooks.setdefault(entry.event, [])
        present = any(
            hook.get("command") == entry.command
            for group in groups
            for hook in group.get("hooks", [])
        )
        if present:
            continue
        group: dict[str, Any] = {"hooks": [{"type": "command", "command": entry.command}]}
        if entry.matcher is not None:
            group = {"matcher": entry.matcher, **group}
        groups.append(group)


def _remove_hooks(data: dict[str, Any], commands: set[str], name: str | None = None) -> None:
    key = name or "hooks"
    hooks = data.get(key, {})
    for event in list(hooks):
        if not isinstance(hooks[event], list):  # e.g. a named group's "enabled" flag
            continue
        groups = _without_commands(hooks[event], commands)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if key in data and not data[key]:
        del data[key]


def _without_commands(groups: list[dict[str, Any]], commands: set[str]) -> list[dict[str, Any]]:
    """Matcher groups minus the given hook commands; groups left empty are dropped."""
    kept_groups = []
    for group in groups:
        kept = [h for h in group.get("hooks", []) if h.get("command") not in commands]
        if kept:
            kept_groups.append({**group, "hooks": kept})
    return kept_groups


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


# -- sync ------------------------------------------------------------------------


def sync(
    desired: list[Owned],
    ledger: Ledger,
    *,
    agents_in_scope: set[str],
    dry_run: bool = False,
    force: bool = False,
    report: Report | None = None,
) -> Report:
    """Makes the filesystem match ``desired`` for ``agents_in_scope``.

    Ledger entries of agents outside ``agents_in_scope`` are left untouched, so
    installing one agent never modifies another agent's files.
    """
    report = report or Report()
    desired_keys = {(_kind(owned.artifact), ledger.key(owned.artifact.path)) for owned in desired}
    kept: list[dict[str, Any]] = []
    for entry in ledger.entries:
        upgrading = entry["kind"] == "link" and ("dir", entry["path"]) in desired_keys
        if (
            entry["agent"] not in agents_in_scope
            or (entry["kind"], entry["path"]) in desired_keys
            or upgrading
        ):
            kept.append(entry)
            continue
        if not _remove_entry(entry, ledger, report, dry_run):
            kept.append(entry)
    ledger.entries = kept

    flags = _ApplyFlags(dry_run=dry_run, force=force)
    for owned in desired:
        _apply_owned(owned, ledger, report, flags)
    return report


def _apply_owned(owned: Owned, ledger: Ledger, report: Report, flags: _ApplyFlags) -> None:
    artifact = owned.artifact
    if isinstance(artifact, FileArtifact):
        _apply_file(owned.agent, artifact, ledger, report, flags.dry_run, flags.force)
    elif isinstance(artifact, LinkArtifact):
        _apply_link(owned.agent, artifact, ledger, report, flags.dry_run, flags.force)
    elif isinstance(artifact, DirArtifact):
        _apply_dir(owned, ledger, report, flags)
    elif isinstance(artifact, BlockArtifact):
        _apply_block(owned.agent, artifact, ledger, report, flags.dry_run)
    else:
        _apply_hooks(owned.agent, artifact, ledger, report, flags.dry_run)


def _kind(artifact: Artifact) -> str:
    if isinstance(artifact, FileArtifact):
        return "file"
    if isinstance(artifact, BlockArtifact):
        return "block"
    if isinstance(artifact, LinkArtifact):
        return "link"
    if isinstance(artifact, DirArtifact):
        return "dir"
    return "hooks"


def _record(ledger: Ledger, entry: dict[str, Any]) -> None:
    ledger.entries = [
        e for e in ledger.entries if (e["kind"], e["path"]) != (entry["kind"], entry["path"])
    ]
    ledger.entries.append(entry)
    ledger.entries.sort(key=lambda e: (e["agent"], e["kind"], e["path"]))


def _apply_file(
    agent: str, artifact: FileArtifact, ledger: Ledger, report: Report, dry_run: bool, force: bool
) -> None:
    current = _read(artifact.path)
    previous = ledger.find("file", artifact.path)
    target_sha = sha256(artifact.text)
    if current == artifact.text:
        report.add("unchanged", artifact.path)
    elif current is not None and previous is None and not force:
        report.warnings.append(
            f"{artifact.path} exists and was not created by ai-governance; left untouched "
            "(use --force to replace it)."
        )
        return
    elif current is not None and previous is not None and sha256(current) != previous["sha256"]:
        if not force:
            report.warnings.append(
                f"{artifact.path} was edited locally; kept your version (use --force to replace)."
            )
            return
        if not dry_run:
            _write(artifact.path, artifact.text)
        report.add("replaced", artifact.path)
    else:
        if not dry_run:
            _write(artifact.path, artifact.text)
        report.add("created" if current is None else "updated", artifact.path)
    _record(
        ledger,
        {"agent": agent, "kind": "file", "path": ledger.key(artifact.path), "sha256": target_sha},
    )


def _apply_link(
    agent: str, artifact: LinkArtifact, ledger: Ledger, report: Report, dry_run: bool, force: bool
) -> None:
    path = artifact.path
    if path.is_symlink() and os.readlink(path) == artifact.target:
        report.add("unchanged", path)
    elif (
        (path.exists() or path.is_symlink())
        and ledger.find("link", path) is None
        and ledger.find("file", path) is None  # our own old copy: migrate it to a link
        and not force
    ):
        report.warnings.append(
            f"{path} exists and was not created by ai-governance; left untouched "
            "(use --force to replace it)."
        )
        return
    else:
        existed = path.exists() or path.is_symlink()
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            if existed:
                path.unlink()
            path.symlink_to(artifact.target)
        report.add("updated" if existed else "linked", path)
    ledger.entries = [
        e for e in ledger.entries if (e["kind"], e["path"]) != ("file", ledger.key(path))
    ]
    _record(
        ledger,
        {"agent": agent, "kind": "link", "path": ledger.key(path), "target": artifact.target},
    )


@dataclass(frozen=True)
class _ApplyFlags:
    dry_run: bool = False
    force: bool = False


def _copy_dir_tree(source: Path, dest: Path) -> None:
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest, symlinks=True)


def _dir_conflict(
    path: Path, prev_dir: dict[str, Any] | None, prev_link: dict[str, Any] | None
) -> str | None:
    if not (path.exists() or path.is_symlink()):
        return None
    if prev_dir is not None:
        edited = path.is_symlink() or not path.is_dir() or tree_digest(path) != prev_dir["sha256"]
        return (
            f"{path} was edited locally; kept your version (use --force to replace)."
            if edited
            else None
        )
    if prev_link is not None and path.is_symlink():
        return None
    return (
        f"{path} exists and was not created by ai-governance; left untouched "
        "(use --force to replace it)."
    )


def _dir_action(
    path: Path, prev_dir: dict[str, Any] | None, target_sha: str, conflict: str | None
) -> str:
    if conflict:
        return "replaced"
    if not (path.exists() or path.is_symlink()):
        return "created"
    if prev_dir is not None and prev_dir["sha256"] == target_sha:
        return "unchanged"
    return "updated"


def _apply_dir(
    owned: Owned, ledger: Ledger, report: Report, flags: _ApplyFlags | None = None
) -> None:
    artifact = owned.artifact
    if not isinstance(artifact, DirArtifact):
        return
    flags = flags or _ApplyFlags()
    path = artifact.path
    target_sha = tree_digest(artifact.source)
    prev_dir = ledger.find("dir", path)
    conflict = _dir_conflict(path, prev_dir, ledger.find("link", path))
    if conflict and not flags.force:
        report.warnings.append(conflict)
        return
    action = _dir_action(path, prev_dir, target_sha, conflict)
    if action != "unchanged" and not flags.dry_run:
        _copy_dir_tree(artifact.source, path)
    report.add(action, path)
    key = ledger.key(path)
    ledger.entries = [e for e in ledger.entries if (e["kind"], e["path"]) != ("link", key)]
    _record(
        ledger,
        {
            "agent": owned.agent,
            "kind": "dir",
            "path": key,
            "sha256": target_sha,
            "source": str(artifact.source),
        },
    )


def _apply_block(
    agent: str, artifact: BlockArtifact, ledger: Ledger, report: Report, dry_run: bool
) -> None:
    current = _read(artifact.path) or ""
    start, end = artifact.markers
    outside = BlockInjector.remove(current, start=start, end=end)
    if artifact.conflict and re.search(artifact.conflict, outside, re.MULTILINE):
        report.warnings.append(
            f"{artifact.path} already defines what this block sets; left untouched."
        )
        return
    updated = BlockInjector.inject(
        current, artifact.body, start=start, end=end, prepend=artifact.prepend
    )
    if updated == current:
        report.add("unchanged", artifact.path)
    else:
        if not dry_run:
            _write(artifact.path, updated)
        report.add("updated block in" if start in current else "added block to", artifact.path)
    _record(
        ledger,
        {
            "agent": agent,
            "kind": "block",
            "path": ledger.key(artifact.path),
            "sha256": sha256(artifact.body),
            "markers": list(artifact.markers),
        },
    )


def _apply_hooks(
    agent: str, artifact: HooksArtifact, ledger: Ledger, report: Report, dry_run: bool
) -> None:
    raw = _read(artifact.path)
    data = json.loads(raw) if raw and raw.strip() else {}
    previous = ledger.find("hooks", artifact.path)
    wanted = {entry.command for entry in artifact.entries}
    if previous:
        _remove_hooks(data, set(previous.get("commands", [])) - wanted, artifact.group)
    _merge_hooks(data, artifact.entries, artifact.group)
    text = _dump_json(data)
    if raw == text:
        report.add("unchanged", artifact.path)
    else:
        if not dry_run:
            _write(artifact.path, text)
        report.add("merged hooks into", artifact.path)
    _record(
        ledger,
        {
            "agent": agent,
            "kind": "hooks",
            "path": ledger.key(artifact.path),
            "commands": sorted(wanted),
            **({"group": artifact.group} if artifact.group else {}),
            "created": bool(previous.get("created")) if previous else raw is None,
        },
    )


def _remove_link_entry(
    entry: dict[str, Any], ledger: Ledger, report: Report, dry_run: bool
) -> bool:
    path = ledger.resolve(entry["path"])
    if path.is_symlink() and os.readlink(path) == entry["target"]:
        if not dry_run:
            path.unlink()
            _prune_empty_parents(path.parent, ledger.base)
        report.add("removed", path)
        return True
    if path.exists():
        report.warnings.append(f"{path} was replaced locally; not removed.")
        return False
    return True


def _remove_file_entry(
    entry: dict[str, Any], ledger: Ledger, report: Report, dry_run: bool
) -> bool:
    path = ledger.resolve(entry["path"])
    current = _read(path)
    if current is None:
        return True
    if sha256(current) != entry["sha256"]:
        report.warnings.append(f"{path} was edited locally; not removed.")
        return False
    if not dry_run:
        path.unlink()
        _prune_empty_parents(path.parent, ledger.base)
    report.add("removed", path)
    return True


def _remove_block_entry(
    entry: dict[str, Any], ledger: Ledger, report: Report, dry_run: bool
) -> bool:
    path = ledger.resolve(entry["path"])
    current = _read(path)
    start, end = entry.get("markers", [START, END])
    if current is None or start not in current:
        return True
    cleaned = BlockInjector.remove(current, start=start, end=end)
    if not dry_run:
        if cleaned:
            _write(path, cleaned)
        else:
            path.unlink()
    report.add("removed block from", path)
    return True


def _remove_hooks_entry(
    entry: dict[str, Any], ledger: Ledger, report: Report, dry_run: bool
) -> bool:
    path = ledger.resolve(entry["path"])
    current = _read(path)
    if current is None:
        return True
    data = json.loads(current) if current.strip() else {}
    _remove_hooks(data, set(entry.get("commands", [])), entry.get("group"))
    if not dry_run:
        if not data and entry.get("created"):
            path.unlink()
            _prune_empty_parents(path.parent, ledger.base)
        else:
            _write(path, _dump_json(data))
    report.add("removed hooks from", path)
    return True


def _remove_dir_entry(entry: dict[str, Any], ledger: Ledger, report: Report, dry_run: bool) -> bool:
    path = ledger.resolve(entry["path"])
    if not path.exists() and not path.is_symlink():
        return True
    if path.is_symlink() or not path.is_dir() or tree_digest(path) != entry["sha256"]:
        report.warnings.append(f"{path} was edited locally; not removed.")
        return False
    if not dry_run:
        shutil.rmtree(path)
        _prune_empty_parents(path.parent, ledger.base)
    report.add("removed", path)
    return True


_REMOVE_HANDLERS = {
    "link": _remove_link_entry,
    "file": _remove_file_entry,
    "block": _remove_block_entry,
    "dir": _remove_dir_entry,
}


def _remove_entry(entry: dict[str, Any], ledger: Ledger, report: Report, dry_run: bool) -> bool:
    """Removes a previously written artifact. Returns False when it had to be kept."""
    handler = _REMOVE_HANDLERS.get(entry["kind"], _remove_hooks_entry)
    return handler(entry, ledger, report, dry_run)


def _prune_empty_parents(directory: Path, stop: Path | None) -> None:
    limit = (stop or Path.home()).resolve()
    current = directory.resolve()
    while current != limit and limit in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
