#!/usr/bin/env python3
"""Run the design-rules eval: task x condition x repetition.

For each combination, copies the fixture into a fresh temp git repo, sets up
the condition (rules / gate hook), invokes `claude -p` non-interactively with
the task prompt, then measures design violations (via `ws design --json` on
files changed since the initial commit), added lines, hidden-test pass rate,
and cost/turn/token metrics reported by the Claude CLI. Appends one row per
run to results/results.csv.

Usage:
    python run.py [--tasks t1,t2] [--conditions c1,c2] [--reps N]
                   [--model MODEL] [--dry-run]
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVAL_ROOT.parent.parent
FIXTURE = EVAL_ROOT / "fixture"
TASKS_DIR = EVAL_ROOT / "tasks"
HIDDEN_DIR = EVAL_ROOT / "hidden_tests"
RESULTS_DIR = EVAL_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "results.csv"

RULE_FILES = [
    REPO_ROOT / "packages/ai-governance/src/ai_governance/catalog/1-core/01-clean-code-solid.md",
    REPO_ROOT
    / "packages/ai-governance/src/ai_governance/catalog/1-core/11-self-documenting-code.md",
]

ALL_TASKS = ["discounts", "csv_import", "payment_client"]
ALL_CONDITIONS = ["none", "rules", "gate", "rules+gate"]

CSV_FIELDS = [
    "task",
    "condition",
    "rep",
    "model",
    "violations_total",
    "violations_by_metric",
    "added_lines",
    "hidden_tests_passed",
    "hidden_tests_total",
    "cost_usd",
    "num_turns",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "run_dir",
    "error",
]


@dataclass
class RunResult:
    task: str
    condition: str
    rep: int
    model: str
    violations_total: int = 0
    violations_by_metric: str = "{}"
    added_lines: int = 0
    hidden_tests_passed: int = 0
    hidden_tests_total: int = 0
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    run_dir: str = ""
    error: str = ""


def make_ws_shim(shim_dir: Path) -> None:
    """Create a `ws` executable on PATH that forwards to `uv run --project REPO_ROOT ws`."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "ws"
    shim.write_text(f"#!/bin/sh\nexec uv run --project '{REPO_ROOT}' ws \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def setup_condition(run_dir: Path, condition: str, shim_dir: Path) -> None:
    settings_dir = run_dir / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)

    if condition in ("rules", "rules+gate"):
        rules_dir = settings_dir / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        for rule_file in RULE_FILES:
            shutil.copy(rule_file, rules_dir / rule_file.name)

    settings: dict = {}
    if condition in ("gate", "rules+gate"):
        hook_script = settings_dir / "design_gate.sh"
        hook_script.write_text(
            "#!/bin/sh\n"
            f'export PATH="{shim_dir}:$PATH"\n'
            f'cd "{run_dir}" || exit 0\n'
            "OUT=$(ws design --changed --json 2>&1)\n"
            'STATUS=$(printf "%s" "$OUT" | python3 -c '
            "\"import json,sys; print(json.load(sys.stdin).get('status','pass'))\" "
            "2>/dev/null || echo pass)\n"
            'if [ "$STATUS" != "pass" ]; then\n'
            '  echo "$OUT" 1>&2\n'
            "  exit 2\n"
            "fi\n"
            "exit 0\n"
        )
        hook_script.chmod(hook_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": str(hook_script),
                            }
                        ]
                    }
                ]
            }
        }
    (settings_dir / "settings.json").write_text(json.dumps(settings, indent=2))


def git(run_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=run_dir, capture_output=True, text=True, check=False)


def build_run_dir(task: str, condition: str, rep: int, shim_dir: Path) -> Path:
    run_dir = Path(tempfile.mkdtemp(prefix=f"design-eval-{task}-{condition}-{rep}-"))
    shutil.copytree(FIXTURE, run_dir, dirs_exist_ok=True)
    git(run_dir, "init", "-q")
    git(run_dir, "config", "user.email", "eval@example.com")
    git(run_dir, "config", "user.name", "Design Eval")
    git(run_dir, "add", "-A")
    git(run_dir, "commit", "-q", "-m", "initial fixture")
    setup_condition(run_dir, condition, shim_dir)
    return run_dir


def claude_command(run_dir: Path, task_prompt: str, model: str) -> list[str]:
    return [
        "claude",
        "-p",
        task_prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--permission-mode",
        "bypassPermissions",
        "--setting-sources",
        "project",
    ]


def run_claude(run_dir: Path, task_prompt: str, model: str, shim_dir: Path) -> dict:
    import os

    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}:{env.get('PATH', '')}"
    cmd = claude_command(run_dir, task_prompt, model)
    proc = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, env=env, timeout=1200)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"claude failed: {proc.stderr[-2000:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"could not parse claude JSON output: {exc}\n{proc.stdout[-2000:]}"
        ) from exc


def measure_design(run_dir: Path, shim_dir: Path) -> tuple[int, dict]:
    import os

    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}:{env.get('PATH', '')}"
    proc = subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "ws", "design", "--changed", "--json"],
        cwd=run_dir,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return 0, {}
    violations = data.get("violations", [])
    by_metric: dict[str, int] = {}
    for v in violations:
        metric = v.get("metric", v.get("check", "unknown"))
        by_metric[metric] = by_metric.get(metric, 0) + 1
    return len(violations), by_metric


def measure_added_lines(run_dir: Path) -> int:
    proc = git(run_dir, "diff", "--numstat", "HEAD")
    added = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 1 and parts[0].isdigit():
            added += int(parts[0])
    return added


def measure_hidden_tests(run_dir: Path, task: str) -> tuple[int, int]:
    hidden_src = HIDDEN_DIR / task
    if not hidden_src.exists():
        return 0, 0
    dest = run_dir / "tests" / f"_hidden_{task}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in hidden_src.glob("*.py"):
        shutil.copy(f, dest / f.name)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(dest), "--no-header"],
        cwd=run_dir,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(run_dir / "src")},
        check=False,
    )
    total = passed = 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("collected "):
            with contextlib.suppress(IndexError, ValueError):
                total = int(line.split()[1])
    summary_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    import re

    m = re.search(r"(\d+) passed", summary_line)
    if m:
        passed = int(m.group(1))
    fail_m = re.search(r"(\d+) failed", summary_line)
    failed = int(fail_m.group(1)) if fail_m else 0
    if total == 0:
        total = passed + failed
    return passed, total


def run_one(task: str, condition: str, rep: int, model: str, shim_dir: Path) -> RunResult:
    result = RunResult(task=task, condition=condition, rep=rep, model=model)
    run_dir = build_run_dir(task, condition, rep, shim_dir)
    result.run_dir = str(run_dir)
    try:
        task_prompt = (TASKS_DIR / f"{task}.md").read_text()
        claude_json = run_claude(run_dir, task_prompt, model, shim_dir)
        # Stage everything (including new files) so diff/status against HEAD
        # captures untracked files the agent created, without committing.
        git(run_dir, "add", "-A")
        result.cost_usd = claude_json.get("total_cost_usd", 0.0)
        result.num_turns = claude_json.get("num_turns", 0)
        result.duration_ms = claude_json.get("duration_ms", 0)
        usage = claude_json.get("usage", {}) or {}
        result.input_tokens = usage.get("input_tokens", 0)
        result.output_tokens = usage.get("output_tokens", 0)

        violations_total, by_metric = measure_design(run_dir, shim_dir)
        result.violations_total = violations_total
        result.violations_by_metric = json.dumps(by_metric)
        result.added_lines = measure_added_lines(run_dir)
        passed, total = measure_hidden_tests(run_dir, task)
        result.hidden_tests_passed = passed
        result.hidden_tests_total = total
    except Exception as exc:  # noqa: BLE001 - record and continue
        result.error = str(exc)[:500]
    return result


def append_csv(result: RunResult) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not RESULTS_CSV.exists()
    with RESULTS_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELDS))
        if is_new:
            writer.writeheader()
        writer.writerow(vars(result))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default=",".join(ALL_TASKS))
    parser.add_argument("--conditions", default=",".join(ALL_CONDITIONS))
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]

    shim_dir = Path(tempfile.mkdtemp(prefix="design-eval-shim-"))
    make_ws_shim(shim_dir)

    for task in tasks:
        for condition in conditions:
            for rep in range(1, args.reps + 1):
                if args.dry_run:
                    run_dir = Path(f"<tmp:{task}-{condition}-{rep}>")
                    cmd = claude_command(run_dir, f"<contents of tasks/{task}.md>", args.model)
                    print(f"[dry-run] {task} x {condition} x rep{rep}")
                    print("  setup: copy fixture -> git init -> setup_condition")
                    print(f"  cmd: {' '.join(cmd)}")
                    continue
                print(f"== {task} x {condition} x rep{rep} ==", file=sys.stderr)
                result = run_one(task, condition, rep, args.model, shim_dir)
                append_csv(result)
                if result.error:
                    print(f"  error: {result.error}", file=sys.stderr)
                else:
                    print(
                        f"  violations={result.violations_total} "
                        f"added_lines={result.added_lines} "
                        f"hidden={result.hidden_tests_passed}/{result.hidden_tests_total} "
                        f"cost=${result.cost_usd:.3f}",
                        file=sys.stderr,
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
