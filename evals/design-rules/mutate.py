"""Tiny stdlib mutation step: does the agent's own test suite protect behavior?

Applies N deterministic mutations (seeded sample of AST sites) to production
modules, one at a time, runs the given pytest command per mutant with a
timeout, and reports killed/total. A mutant is killed when the tests fail or
time out; it survives when they still pass.
"""

from __future__ import annotations

import ast
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

SEED = 20260930
N_MUTANTS = 10
MUTANT_TIMEOUT_S = 60

_COMPARE_SWAPS = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
}
_BINOP_SWAPS = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv}


def _sites(tree: ast.AST) -> list[ast.AST]:
    """Mutable nodes in a stable (walk) order."""
    sites: list[ast.AST] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Compare)
            and type(node.ops[0]) in _COMPARE_SWAPS
            or isinstance(node, ast.BinOp)
            and type(node.op) in _BINOP_SWAPS
            or isinstance(node, ast.Constant)
            and isinstance(node.value, bool)
            or (
                isinstance(node, ast.Return)
                and node.value is not None
                and not (isinstance(node.value, ast.Constant) and node.value.value is None)
            )
        ):
            sites.append(node)
    return sites


def _apply(node: ast.AST) -> None:
    if isinstance(node, ast.Compare):
        node.ops[0] = _COMPARE_SWAPS[type(node.ops[0])]()
    elif isinstance(node, ast.BinOp):
        node.op = _BINOP_SWAPS[type(node.op)]()
    elif isinstance(node, ast.Constant):
        node.value = not node.value
    elif isinstance(node, ast.Return):
        node.value = ast.Constant(value=None)


def make_mutants(source: str, count: int, rng: random.Random) -> list[str]:
    """Return up to `count` distinct mutated sources of `source`."""
    n_sites = len(_sites(ast.parse(source)))
    chosen = sorted(rng.sample(range(n_sites), min(count, n_sites)))
    mutants = []
    for index in chosen:
        tree = ast.parse(source)
        _apply(_sites(tree)[index])
        mutants.append(ast.unparse(ast.fix_missing_locations(tree)))
    return mutants


def _clear_bytecode(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _tests_pass(run_dir: Path, pytest_args: list[str]) -> bool:
    _clear_bytecode(run_dir)
    env = {**os.environ, "PYTHONPATH": str(run_dir / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *pytest_args],
            cwd=run_dir,
            capture_output=True,
            env=env,
            timeout=MUTANT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def mutation_score(run_dir: Path, modules: list[Path], pytest_args: list[str]) -> tuple[int, int]:
    """Return (killed, total). (0, 0) when nothing was mutable or the baseline is red."""
    if not modules or not _tests_pass(run_dir, pytest_args):
        return 0, 0
    rng = random.Random(SEED)
    plan: list[tuple[Path, str]] = []
    originals: dict[Path, str] = {}
    for module in sorted(modules):
        originals[module] = module.read_text()
    per_module = [(m, make_mutants(originals[m], N_MUTANTS, rng)) for m in sorted(modules)]
    # Round-robin across modules so N stays bounded and every module is touched.
    for round_index in range(N_MUTANTS):
        for module, mutants in per_module:
            if round_index < len(mutants) and len(plan) < N_MUTANTS:
                plan.append((module, mutants[round_index]))
    killed = 0
    try:
        for module, mutant in plan:
            module.write_text(mutant)
            if not _tests_pass(run_dir, pytest_args):
                killed += 1
            module.write_text(originals[module])
    finally:
        for module, text in originals.items():
            module.write_text(text)
        _clear_bytecode(run_dir)
    return killed, len(plan)
