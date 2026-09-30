"""``ws design`` — deterministic design/complexity metrics for every language."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path

from workspace_engine.common import run_command_safe
from workspace_engine.design.config import DesignConfig
from workspace_engine.design.metrics import measure, supported
from workspace_engine.design.report import format_text, to_dict
from workspace_engine.services.changes import changed_files


def _excluded_dir_names(exclude: tuple[str, ...]) -> frozenset[str]:
    """Bare directory names from ``**/name/**`` patterns, for cheap walk pruning."""
    names = set()
    for pattern in exclude:
        parts = pattern.split("/")
        if len(parts) == 3 and parts[0] == "**" and parts[2] == "**":
            names.add(parts[1])
    return frozenset(names)


def _walk(root: Path, base: Path, exclude: tuple[str, ...]) -> list[Path]:
    skip_dirs = _excluded_dir_names(exclude)
    found: list[Path] = []
    for current, dirs, file_names in os.walk(base):
        current_path = Path(current)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in skip_dirs)
        for name in file_names:
            candidate = current_path / name
            relative = f"/{candidate.relative_to(root).as_posix()}"
            if not any(fnmatch.fnmatch(relative, pattern) for pattern in exclude):
                found.append(candidate)
    return found


def _repo_files(root: Path, exclude: tuple[str, ...]) -> list[Path]:
    code, out, _ = run_command_safe(["git", "ls-files"], cwd=root, isolated_git=True)
    if code == 0 and out.strip():
        return [root / line for line in out.splitlines() if line]
    return _walk(root, root, exclude)


def _collect(root: Path, args: argparse.Namespace, exclude: tuple[str, ...]) -> list[Path]:
    if args.files_from:
        lines = Path(args.files_from).read_text(encoding="utf-8").splitlines()
        return [root / line.strip() for line in lines if line.strip()]
    if args.changed:
        return [root / relative for relative in changed_files(root)]
    if args.paths:
        collected: list[Path] = []
        for raw in args.paths:
            candidate = (root / raw) if not Path(raw).is_absolute() else Path(raw)
            if candidate.is_dir():
                collected.extend(_walk(root, candidate, exclude))
            else:
                collected.append(candidate)
        return collected
    return _repo_files(root, exclude)


def design(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ws design", description="Deterministic design metrics")
    parser.add_argument("--dir", "-d", default=".", help="Repository root")
    parser.add_argument("--changed", action="store_true", help="Measure only changed files")
    parser.add_argument("--files-from", help="Newline-separated file, relative to root")
    parser.add_argument("paths", nargs="*", help="Files or directories to measure")
    parser.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")
    args = parser.parse_args(argv)
    root = Path(args.dir).resolve()

    config = DesignConfig.load(root)
    if config.mode == "off":
        print("design: off")
        return 0

    candidates = _collect(root, args, config.exclude)
    files = [path for path in candidates if path.is_file() and supported(path)]
    violations = measure(root, files, config)

    if args.json:
        print(json.dumps(to_dict(violations, config, len(files)), ensure_ascii=False))
    else:
        print(format_text(violations, config, len(files)))

    if violations and config.mode == "block":
        return 1
    return 0
