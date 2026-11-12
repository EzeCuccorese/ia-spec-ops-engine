"""``ws check`` and ``ws changed`` — quality gate and change set for agents and humans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workspace_engine.condense import logs
from workspace_engine.condense.engine import condense
from workspace_engine.services.changes import (
    SCHEMA_VERSION,
    changed_files,
    tree_fingerprint,
)
from workspace_engine.services.git_hooks import QG_STAGES, local_hook_path, run_quality_gate


def _pass_marker(root: Path) -> Path:
    return local_hook_path(root).parent.parent / "check-pass"


def _cache_entry(root: Path, scope: str, skip: str | None, fingerprint: str) -> str:
    return f"{root}:{scope}:{skip or ''}:{fingerprint}"


def _is_cached(marker: Path, entry: str) -> bool:
    if not marker.is_file():
        return False
    return entry in {line.strip() for line in marker.read_text().splitlines() if line.strip()}


def _record_cache(marker: Path, entry: str) -> None:
    existing = (
        [line.strip() for line in marker.read_text().splitlines() if line.strip()]
        if marker.is_file()
        else []
    )
    updated = [line for line in existing if line != entry][-15:] + [entry]
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("\n".join(updated) + "\n")


def _build_check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ws check", description="Run the quality gate")
    parser.add_argument("--dir", "-d", default=".", help="Repository root")
    parser.add_argument("--changed", action="store_true", help="Lint/test only changed files")
    parser.add_argument("--skip", help=f"Stages to skip: {','.join(QG_STAGES)}")
    parser.add_argument("--budget", type=int, default=1500, help="Max characters of output")
    parser.add_argument(
        "--cache", action="store_true", help="Skip when the tree is unchanged since the last pass"
    )
    parser.add_argument("--json", action="store_true", help="Emit the versioned JSON contract")
    return parser


def _execute_gate(
    root: Path, args: argparse.Namespace, marker: Path, entry: str
) -> tuple[str, int, str, str | None]:
    scope = "changed" if args.changed else "all"
    captured: list[str] = []
    code = run_quality_gate(root, scope=scope, skip=args.skip, output="errors", capture=captured)
    output = captured[0] if captured else ""
    text = condense(output, "ws check", code, args.budget).text
    log_id = logs.save(output, "ws check") if code != 0 else None
    status = "passed" if code == 0 else "failed"
    if code == 0:
        _record_cache(marker, entry)
        text = "✓ gate: passed"
    return status, code, text, log_id


def check(argv: list[str]) -> int:
    args = _build_check_parser().parse_args(argv)
    root = Path(args.dir).resolve()
    scope = "changed" if args.changed else "all"
    fingerprint = tree_fingerprint(root)
    marker = _pass_marker(root)
    entry = _cache_entry(root, scope, args.skip, fingerprint)

    if args.cache and _is_cached(marker, entry):
        status, code, text, log_id = "skipped", 0, "✓ gate: unchanged since last pass", None
    else:
        status, code, text, log_id = _execute_gate(root, args, marker, entry)

    if args.json:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "exit_code": code,
            "text": text,
            "log_id": log_id,
            "fingerprint": fingerprint,
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(text)
        if log_id:
            print(f"[exit={code} · full log: ws log {log_id}]")
    return code


def changed(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ws changed", description="Files changed vs. base")
    parser.add_argument("--dir", "-d", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    files = changed_files(Path(args.dir).resolve())
    if args.json:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "files": files}))
    else:
        print("\n".join(files))
    return 0
