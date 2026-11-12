"""``ws check`` and ``ws changed`` — quality gate and change set for agents and humans."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from workspace_engine._config_core import ConfigError
from workspace_engine.condense import logs
from workspace_engine.condense.engine import condense
from workspace_engine.services.changes import (
    SCHEMA_VERSION,
    changed_files,
    tree_fingerprint,
)
from workspace_engine.services.git_hooks import QG_STAGES, local_hook_path, run_quality_gate
from workspace_engine.settings import get


def _pass_marker(root: Path) -> Path:
    return local_hook_path(root).parent.parent / "check-pass"


def _effective_skip(root: Path, flag_skip: str | None) -> str | None:
    if flag_skip is not None:
        items = flag_skip.split(",")
    else:
        try:
            configured = get("gate.skip", root)
        except (ConfigError, ValueError):
            return None
        items = [str(s) for s in configured] if isinstance(configured, list) else []
    return ",".join(sorted({s.strip() for s in items if s.strip() and s.strip() != "none"}))


def _cache_entry(root: Path, scope: str, skip: str, fingerprint: str) -> str:
    return f"{root}:{scope}:{skip}:{fingerprint}"


def _read_entries(marker: Path) -> list[str]:
    if not marker.is_file():
        return []
    return [
        line.strip() for line in marker.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _record_cache(marker: Path, entry: str) -> None:
    existing = _read_entries(marker)
    updated = [line for line in existing if line != entry][-15:] + [entry]
    marker.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=marker.parent, prefix=".check-pass-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(updated) + "\n")
        os.replace(tmp_path, marker)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
    root: Path, scope: str, args: argparse.Namespace, entry: str | None
) -> tuple[str, int, str, str | None]:
    captured: list[str] = []
    code = run_quality_gate(root, scope=scope, skip=args.skip, output="errors", capture=captured)
    output = captured[0] if captured else ""
    text = condense(output, "ws check", code, args.budget).text
    log_id = logs.save(output, "ws check") if code != 0 else None
    status = "passed" if code == 0 else "failed"
    if code == 0:
        if entry is not None:
            _record_cache(_pass_marker(root), entry)
        text = "✓ gate: passed"
    return status, code, text, log_id


def check(argv: list[str]) -> int:
    args = _build_check_parser().parse_args(argv)
    root = Path(args.dir).resolve()
    scope = "changed" if args.changed else "all"
    fingerprint = tree_fingerprint(root)
    skip_key = _effective_skip(root, args.skip)
    entry = _cache_entry(root, scope, skip_key, fingerprint) if skip_key is not None else None

    if args.cache and entry is not None and entry in _read_entries(_pass_marker(root)):
        status, code, text, log_id = "skipped", 0, "✓ gate: unchanged since last pass", None
    else:
        status, code, text, log_id = _execute_gate(root, scope, args, entry)

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
