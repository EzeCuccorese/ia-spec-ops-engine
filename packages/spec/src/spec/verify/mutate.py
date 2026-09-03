from __future__ import annotations

import io
import os
import subprocess
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

# Operator mutations: token OP -> replacement
OP_MUTATIONS: dict[str, str] = {
    "<=": "<",
    ">=": ">",
    "<": "<=",
    ">": ">=",
    "==": "!=",
    "!=": "==",
    "+": "-",
    "-": "+",
}

# Keyword / Boolean mutations: token NAME -> replacement
NAME_MUTATIONS: dict[str, str] = {
    "and": "or",
    "or": "and",
    "True": "False",
    "False": "True",
}


@dataclass(frozen=True)
class Mutant:
    row: int  # 1-based line number
    col_start: int  # 0-based column start
    col_end: int  # 0-based column end
    original: str
    replacement: str
    category: str

    def apply(self, lines: list[str]) -> str:
        out = list(lines)
        line = out[self.row - 1]
        out[self.row - 1] = line[: self.col_start] + self.replacement + line[self.col_end :]
        return "".join(out)

    def describe(self, path: str | Path) -> str:
        return f"{path}:{self.row} {self.category} ({self.original!r} -> {self.replacement!r})"


@dataclass
class MutationResult:
    target_path: str
    total: int
    killed: int
    survived: int
    score: float
    survivors: list[Mutant] = field(default_factory=list)
    skipped_noncompiling: int = 0
    truncated: int = 0

    @property
    def passed(self) -> bool:
        return self.survived == 0


def _int_mutation(literal: str) -> str | None:
    try:
        value = int(literal, 0)
    except ValueError:
        return None
    return str(value + 1)


def generate_mutants(source: str, *, target_lines: set[int] | None = None) -> list[Mutant]:
    mutants: list[Mutant] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return mutants

    for tok in tokens:
        if tok.start[0] != tok.end[0]:
            continue
        row = tok.start[0]
        if target_lines is not None and row not in target_lines:
            continue

        col_start, col_end = tok.start[1], tok.end[1]
        text = tok.string

        if tok.type == tokenize.OP and text in OP_MUTATIONS:
            mutants.append(
                Mutant(row, col_start, col_end, text, OP_MUTATIONS[text], "operator")
            )
        elif tok.type == tokenize.NAME and text in NAME_MUTATIONS:
            mutants.append(
                Mutant(row, col_start, col_end, text, NAME_MUTATIONS[text], "keyword")
            )
        elif tok.type == tokenize.NUMBER:
            repl = _int_mutation(text)
            if repl is not None:
                mutants.append(
                    Mutant(row, col_start, col_end, text, repl, "number")
                )

    lines = source.splitlines(keepends=True)
    for idx, raw in enumerate(lines, start=1):
        if target_lines is not None and idx not in target_lines:
            continue
        stripped = raw.lstrip()
        if not stripped.startswith("return "):
            continue
        rest = stripped[len("return ") :].strip()
        if rest in ("", "None"):
            continue
        indent = len(raw) - len(stripped)
        content = raw.rstrip("\r\n")
        mutants.append(
            Mutant(
                idx,
                indent,
                len(content),
                content[indent:],
                "return None",
                "return",
            )
        )
    return mutants


def compiles(source: str, filename: str = "<mutation>") -> bool:
    try:
        compile(source, filename, "exec")
        return True
    except SyntaxError:
        return False


def run_test_command(cmd: list[str], cwd: Path | None = None) -> bool:
    """Returns True if tests pass (exit code 0)."""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if cwd:
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{cwd}:{existing_pp}" if existing_pp else str(cwd)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def determine_default_test_cmd(root: Path) -> list[str]:
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        check=False,
    )
    if res.returncode == 0:
        return [sys.executable, "-m", "pytest", "-q"]
    return [sys.executable, "-m", "unittest", "discover", "-q"]


def run_mutation_analysis(
    target: str | Path,
    *,
    test_cmd: list[str] | None = None,
    cwd: Path | None = None,
    max_mutants: int = 100,
    target_lines: set[int] | None = None,
    verbose: bool = False,
) -> MutationResult:
    target_path = Path(target).resolve()
    if not target_path.is_file():
        raise FileNotFoundError(f"Target file not found: {target_path}")

    working_dir = cwd or target_path.parent
    command = test_cmd or determine_default_test_cmd(working_dir)

    original_code = target_path.read_text(encoding="utf-8")
    lines = original_code.splitlines(keepends=True)

    # Sanity check: the test suite must be GREEN before mutating
    if not run_test_command(command, cwd=working_dir):
        raise RuntimeError("Test suite is failing before mutation. Fix tests first.")

    all_mutants = generate_mutants(original_code, target_lines=target_lines)
    valid_mutants = [m for m in all_mutants if compiles(m.apply(lines), str(target_path))]
    skipped_noncompile = len(all_mutants) - len(valid_mutants)

    truncated = 0
    if len(valid_mutants) > max_mutants:
        truncated = len(valid_mutants) - max_mutants
        valid_mutants = valid_mutants[:max_mutants]

    killed: list[Mutant] = []
    survived: list[Mutant] = []

    try:
        for idx, mutant in enumerate(valid_mutants, start=1):
            mutated_code = mutant.apply(lines)
            target_path.write_text(mutated_code, encoding="utf-8")

            # Run tests against mutated code
            if run_test_command(command, cwd=working_dir):
                survived.append(mutant)
                mark = "SURVIVED"
            else:
                killed.append(mutant)
                mark = "KILLED"

            if verbose:
                print(f"  [{idx}/{len(valid_mutants)}] {mark:8} {mutant.describe(target_path)}")
    finally:
        # Guarantee original code is restored even upon abort
        target_path.write_text(original_code, encoding="utf-8")

    total = len(valid_mutants)
    score = (len(killed) / total * 100.0) if total > 0 else 100.0

    return MutationResult(
        target_path=str(target_path),
        total=total,
        killed=len(killed),
        survived=len(survived),
        score=score,
        survivors=survived,
        skipped_noncompiling=skipped_noncompile,
        truncated=truncated,
    )
