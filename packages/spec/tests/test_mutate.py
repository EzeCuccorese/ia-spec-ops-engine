from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from spec.verify.mutate import (
    Mutant,
    compiles,
    generate_mutants,
    run_mutation_analysis,
)


def test_generate_mutants_operators_and_keywords():
    source = "def check(a, b):\n    if a <= b and True:\n        return a + b\n    return 0\n"
    mutants = generate_mutants(source)
    descriptions = [m.replacement for m in mutants]

    # '<=' -> '<'
    assert "<" in descriptions
    # 'and' -> 'or'
    assert "or" in descriptions
    # 'True' -> 'False'
    assert "False" in descriptions
    # '+' -> '-'
    assert "-" in descriptions
    # 'return a + b' -> 'return None'
    assert "return None" in descriptions
    # '0' -> '1'
    assert "1" in descriptions


def test_generate_mutants_ignores_strings_and_comments():
    source = '# This <= is a comment == with True\ntext = "also <= and True in string"\n'
    mutants = generate_mutants(source)
    assert len(mutants) == 0


def test_generate_mutants_line_filter():
    source = "line1 = 1 + 2\nline2 = 3 + 4\nline3 = 5 + 6\n"
    # Only mutate line 2
    mutants = generate_mutants(source, target_lines={2})
    assert len(mutants) > 0
    assert all(m.row == 2 for m in mutants)


def test_compiles_helper():
    assert compiles("x = 1 + 2") is True
    assert compiles("def invalid syntax (:") is False


def test_mutant_apply():
    lines = ["a = 1\n", "if a == 1:\n", "    pass\n"]
    mutant = Mutant(
        row=2,
        col_start=5,
        col_end=7,
        original="==",
        replacement="!=",
        category="operator",
    )
    result = mutant.apply(lines)
    assert "if a != 1:" in result


def test_run_mutation_analysis_full_kill():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        target = dir_path / "math_mod.py"
        target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        test_file = dir_path / "test_mod.py"
        test_file.write_text(
            "import unittest\nfrom math_mod import add\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(1, 2), 3)\n"
            "        self.assertEqual(add(0, 0), 0)\n",
            encoding="utf-8",
        )

        test_cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(dir_path)]
        res = run_mutation_analysis(target, test_cmd=test_cmd, cwd=dir_path)

        assert res.total > 0
        assert res.survived == 0
        assert res.killed == res.total
        assert res.score == 100.0
        assert res.passed is True
        # Verify original file was restored
        assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_run_mutation_analysis_survivor_detected():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        target = dir_path / "weak_mod.py"
        # The return value is tested, but not the boundary
        target.write_text("def is_positive(x):\n    return x > 0\n", encoding="utf-8")

        test_file = dir_path / "test_weak.py"
        # Weak test: only tests with 5 (which is both > 0 and >= 0)
        test_file.write_text(
            "import unittest\nfrom weak_mod import is_positive\n\n"
            "class TestWeak(unittest.TestCase):\n"
            "    def test_pos(self):\n"
            "        self.assertTrue(is_positive(5))\n",
            encoding="utf-8",
        )

        test_cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(dir_path)]
        res = run_mutation_analysis(target, test_cmd=test_cmd, cwd=dir_path)

        assert res.total > 0
        # '>' -> '>=' will survive because is_positive(5) is still True!
        assert res.survived > 0
        assert res.passed is False
        assert any(m.replacement == ">=" for m in res.survivors)
        # Verify original file was restored
        assert target.read_text(encoding="utf-8") == "def is_positive(x):\n    return x > 0\n"
