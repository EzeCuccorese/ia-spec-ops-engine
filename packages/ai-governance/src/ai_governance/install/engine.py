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
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agents import (
    MARKER,
    Artifact,
    BlockArtifact,
    FileArtifact,
    HookEntry,
    HooksArtifact,
    LinkArtifact,
)
from .blocks import BlockInjector

LEDGER_SCHEMA = 1
START = f"<!-- {MARKER}:start -->"
END = f"<!-- {MARKER}:end -->"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
                resolved = path.parent.resolve() / path.name
                return resolved.relative_to(self.base.resolve()).as_posix()
            except ValueError:
                pass
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


def _merge_hooks(data: dict[str, Any], entries: tuple[HookEntry, ...]) -> None:
    hooks = data.setdefault("hooks", {})
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


def _remove_hooks(data: dict[str, Any], commands: set[str]) -> None:
    hooks = data.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if h.get("command") not in commands]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if "hooks" in data and not data["hooks"]:
        del data["hooks"]


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
        if entry["agent"] not in agents_in_scope or (entry["kind"], entry["path"]) in desired_keys:
            kept.append(entry)
            continue
        if not _remove_entry(entry, ledger, report, dry_run):
            kept.append(entry)
    ledger.entries = kept

    for owned in desired:
        artifact = owned.artifact
        if isinstance(artifact, FileArtifact):
            _apply_file(owned.agent, artifact, ledger, report, dry_run, force)
        elif isinstance(artifact, LinkArtifact):
            _apply_link(owned.agent, artifact, ledger, report, dry_run, force)
        elif isinstance(artifact, BlockArtifact):
            _apply_block(owned.agent, artifact, ledger, report, dry_run)
        else:
            _apply_hooks(owned.agent, artifact, ledger, report, dry_run)
    return report


def _kind(artifact: Artifact) -> str:
    if isinstance(artifact, FileArtifact):
        return "file"
    if isinstance(artifact, BlockArtifact):
        return "block"
    if isinstance(artifact, LinkArtifact):
        return "link"
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
    elif (path.exists() or path.is_symlink()) and ledger.find("link", path) is None and not force:
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
    _record(
        ledger,
        {"agent": agent, "kind": "link", "path": ledger.key(path), "target": artifact.target},
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
        _remove_hooks(data, set(previous.get("commands", [])) - wanted)
    _merge_hooks(data, artifact.entries)
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
            "created": bool(previous.get("created")) if previous else raw is None,
        },
    )


def _remove_entry(entry: dict[str, Any], ledger: Ledger, report: Report, dry_run: bool) -> bool:
    """Removes a previously written artifact. Returns False when it had to be kept."""
    path = ledger.resolve(entry["path"])
    if entry["kind"] == "link":
        if path.is_symlink() and os.readlink(path) == entry["target"]:
            if not dry_run:
                path.unlink()
                _prune_empty_parents(path.parent, ledger.base)
            report.add("removed", path)
        elif path.exists():
            report.warnings.append(f"{path} was replaced locally; not removed.")
            return False
        return True
    current = _read(path)
    if entry["kind"] == "file":
        if current is None:
            return True
        if sha256(current) != entry["sha256"]:
            report.warnings.append(f"{path} was edited locally; not removed.")
            return False
        if not dry_run:
            path.unlink()
            _prune_empty_parents(path.parent, ledger.base)
        report.add("removed", path)
    elif entry["kind"] == "block":
        start, end = entry.get("markers", [START, END])
        if current is not None and start in current:
            cleaned = BlockInjector.remove(current, start=start, end=end)
            if not dry_run:
                if cleaned:
                    _write(path, cleaned)
                else:
                    path.unlink()
            report.add("removed block from", path)
    elif current is not None:
        data = json.loads(current) if current.strip() else {}
        _remove_hooks(data, set(entry.get("commands", [])))
        if not dry_run:
            if not data and entry.get("created"):
                path.unlink()
                _prune_empty_parents(path.parent, ledger.base)
            else:
                _write(path, _dump_json(data))
        report.add("removed hooks from", path)
    return True


def _prune_empty_parents(directory: Path, stop: Path | None) -> None:
    limit = (stop or Path.home()).resolve()
    current = directory.resolve()
    while current != limit and limit in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
