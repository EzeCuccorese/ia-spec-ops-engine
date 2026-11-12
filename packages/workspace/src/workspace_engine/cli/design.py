"""``ws design`` — deterministic design/complexity metrics for every language."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path

from workspace_engine.common import run_command_safe
from workspace_engine.design.changes import changed_lines
from workspace_engine.design.config import DesignConfig
from workspace_engine.design.hygiene import hygiene_violations
from workspace_engine.design.layers import layer_violations
from workspace_engine.design.metrics import (
    DiffScope,
    Violation,
    function_at,
    measure,
    supported,
    violations_for,
)
from workspace_engine.design.report import format_focus, format_text, to_dict
from workspace_engine.design.stats import (
    compute_stats,
    format_stats_json,
    format_stats_table,
    format_suggest_toml,
)
from workspace_engine.design.testquality import junk_test_violations
from workspace_engine.services.changes import base_ref, changed_files


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
        candidates = [root / line for line in out.splitlines() if line]
        return [
            c
            for c in candidates
            if not any(
                fnmatch.fnmatch(f"/{c.relative_to(root).as_posix()}", pattern)
                for pattern in exclude
            )
        ]
    return _walk(root, root, exclude)


def _is_excluded(path: Path, root: Path, exclude: tuple[str, ...]) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = path.as_posix()
    candidate = f"/{relative}"
    return any(fnmatch.fnmatch(candidate, p) or fnmatch.fnmatch(relative, p) for p in exclude)


def _collect(root: Path, args: argparse.Namespace, exclude: tuple[str, ...]) -> list[Path]:
    if args.files_from:
        lines = Path(args.files_from).read_text(encoding="utf-8").splitlines()
        candidates = [root / line.strip() for line in lines if line.strip()]
    elif args.changed:
        candidates = [root / relative for relative in changed_files(root)]
    elif args.paths:
        collected: list[Path] = []
        for raw in args.paths:
            candidate = (root / raw) if not Path(raw).is_absolute() else Path(raw)
            if candidate.is_dir():
                collected.extend(_walk(root, candidate, exclude))
            else:
                collected.append(candidate)
        candidates = collected
    else:
        candidates = _repo_files(root, exclude)
    return [p for p in candidates if not _is_excluded(p, root, exclude)]


def _focus(root: Path, spec: str, config: DesignConfig) -> int:
    raw_path, sep, raw_line = spec.rpartition(":")
    if not sep:
        print(f"design: --focus expects path:line, got {spec!r}")
        return 1
    try:
        line = int(raw_line)
    except ValueError:
        print(f"design: --focus expects path:line, got {spec!r}")
        return 1
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / raw_path
    fm = function_at(root, path, line)
    if fm is None:
        print(f"design: no function found at {spec}")
        return 1
    source = path.read_text(encoding="utf-8")
    print(format_focus(fm, config, source))
    return 1 if violations_for(fm, config) else 0


def _run_checks(
    root: Path, args: argparse.Namespace, config: DesignConfig
) -> tuple[list[Violation], int]:
    candidates = _collect(root, args, config.exclude)
    files = [path for path in candidates if path.is_file() and supported(path)]
    changed = changed_lines(root) if (args.changed or args.files_from) else None
    scope = DiffScope(changed, base_ref(root)) if changed is not None else None
    violations = measure(root, files, config, scope)

    all_candidates = [path for path in candidates if path.is_file()]
    violations = violations + hygiene_violations(root, all_candidates, config.checks, changed)
    violations = violations + junk_test_violations(root, all_candidates, config.checks, changed)

    if "architecture" in config.profiles:
        if config.layers is None:
            if not args.json:
                print("layers: not configured ([design.layers])")
        else:
            violations = violations + layer_violations(root, all_candidates, config.layers, changed)
    violations.sort(key=lambda v: (v.path, v.start_line, v.metric))
    return violations, len(files)


def _run_stats(root: Path, args: argparse.Namespace, config: DesignConfig) -> int:
    files = _repo_files(root, config.exclude)
    stats = compute_stats(root, files, config)
    if args.json:
        print(json.dumps(format_stats_json(stats, suggest=args.suggest), ensure_ascii=False))
        return 0
    if args.suggest:
        print(format_suggest_toml(stats.suggested_limits))
    else:
        print(format_stats_table(stats))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ws design", description="Deterministic design metrics")
    parser.add_argument("--dir", "-d", default=".", help="Repository root")
    parser.add_argument("--changed", action="store_true", help="Measure only changed files")
    parser.add_argument("--files-from", help="Newline-separated file, relative to root")
    parser.add_argument("paths", nargs="*", help="Files or directories to measure")
    parser.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")
    parser.add_argument(
        "--focus", help="path:line — focused brief for the function containing that line"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="List every pre-existing violation individually"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Report metric distribution across all tracked files"
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Propose limits from prod p99 as a ready-to-paste [design] TOML block (implies --stats)",
    )
    return parser


def _render_report(
    violations: list[Violation], config: DesignConfig, file_count: int, args: argparse.Namespace
) -> None:
    if args.json:
        print(json.dumps(to_dict(violations, config, file_count), ensure_ascii=False))
    else:
        scoped = bool(args.changed or args.files_from)
        print(format_text(violations, config, file_count, verbose=args.verbose or not scoped))


def design(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(args.dir).resolve()
    config = DesignConfig.load(root)

    if args.focus:
        return _focus(root, args.focus, config)

    if args.stats or args.suggest:
        return _run_stats(root, args, config)

    if config.mode == "off":
        print("design: off")
        return 0

    violations, file_count = _run_checks(root, args, config)
    _render_report(violations, config, file_count, args)

    if config.mode == "block" and any(v.blocking for v in violations):
        return 1
    return 0
