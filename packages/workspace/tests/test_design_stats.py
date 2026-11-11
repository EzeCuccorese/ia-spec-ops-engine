"""Tests for ``ws design --stats`` and ``ws design --suggest``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from workspace_engine.cli import design as design_cli
from workspace_engine.design.config import DesignConfig
from workspace_engine.design.stats import (
    compute_stats,
    format_stats_json,
    format_stats_table,
    format_suggest_toml,
    language_of,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_language_of() -> None:
    assert language_of("foo.py") == "python"
    assert language_of("bar.ts") == "typescript"
    assert language_of("baz.js") == "javascript"
    assert language_of("test.go") == "go"
    assert language_of("A.java") == "java"
    assert language_of("unknown.xyz") == "xyz"


def _create_sample_repo(root: Path) -> tuple[Path, Path, Path]:
    repo = root / "stats_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")

    prod1 = repo / "simple.py"
    prod1.write_text("def add(a, b):\n    return a + b\n")

    prod2 = repo / "complex_prod.py"
    prod2.write_text(
        "def compute(a, b, c, d, e):\n"
        "    if a > 0:\n"
        "        if b > 0:\n"
        "            if c > 0:\n"
        "                if d > 0:\n"
        "                    return a + b + c + d + e\n"
        "    return 0\n"
    )

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    test1 = tests_dir / "test_simple.py"
    test1.write_text("def test_add():\n    assert add(1, 2) == 3\n")

    ignored_dir = repo / "node_modules"
    ignored_dir.mkdir()
    (ignored_dir / "ignored.py").write_text("def bad():\n    pass\n")

    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo, prod1, prod2


def test_stats_distribution_calculation(tmp_path: Path) -> None:
    repo, prod1, prod2 = _create_sample_repo(tmp_path)
    test1 = repo / "tests" / "test_simple.py"
    config = DesignConfig.load(repo)
    stats = compute_stats(repo, [prod1, prod2, test1], config)

    assert "python" in stats.by_language
    py_stats = stats.by_language["python"]
    assert py_stats["prod"].count == 2
    assert py_stats["test"].count == 1

    args_stat = py_stats["prod"].metrics["args"]
    assert args_stat.max == 5
    assert args_stat.exceeded == 1
    assert args_stat.p50 == 3.5

    nesting_stat = py_stats["prod"].metrics["nesting"]
    assert nesting_stat.max == 4
    assert nesting_stat.exceeded == 1

    assert stats.suggested_limits["args"] >= 5
    assert stats.suggested_limits["nesting"] >= 4


def test_cli_stats_and_suggest_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _, _ = _create_sample_repo(tmp_path)

    # CLI --stats --json
    code = design_cli.design(["--dir", str(repo), "--stats", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["by_language"]["python"]["prod"]["count"] == 2
    assert data["by_language"]["python"]["test"]["count"] == 1
    assert "suggested" not in data

    # CLI --suggest --json
    code = design_cli.design(["--dir", str(repo), "--suggest", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert "suggested" in data
    assert data["suggested"]["max_args"] >= 5


def test_cli_stats_and_suggest_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _, _ = _create_sample_repo(tmp_path)

    # CLI --stats table
    code = design_cli.design(["--dir", str(repo), "--stats"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Language" in out
    assert "python" in out
    assert "prod" in out
    assert "test" in out

    # CLI --suggest TOML
    code = design_cli.design(["--dir", str(repo), "--suggest"])
    assert code == 0
    out = capsys.readouterr().out
    assert "[design]" in out
    assert "max_complexity =" in out
    assert "max_args =" in out


def test_stats_empty_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("# Readme\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")

    code = design_cli.design(["--dir", str(repo), "--stats"])
    assert code == 0
    out = capsys.readouterr().out
    assert "No functions found." in out

    code = design_cli.design(["--dir", str(repo), "--stats", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data == {"by_language": {}}

    code = design_cli.design(["--dir", str(repo), "--suggest"])
    assert code == 0
    out = capsys.readouterr().out
    assert "[design]" in out
    assert "max_complexity = 10" in out


def test_stats_formatters_unit() -> None:
    config = DesignConfig()
    stats = compute_stats(Path("."), [], config)
    assert format_stats_table(stats) == "No functions found."
    json_data = format_stats_json(stats, suggest=True)
    assert json_data["suggested"]["max_complexity"] == 10
    toml = format_suggest_toml(stats.suggested_limits)
    assert "[design]" in toml

    # Explicit unit test of helper calculation functions
    from workspace_engine.design.stats import _calculate_metric_stats, _percentiles

    assert _percentiles([]) == (0.0, 0.0, 0.0)
    assert _calculate_metric_stats([], 10).max == 0
    single_stat = _calculate_metric_stats([5], 4)
    assert single_stat.max == 5
    assert single_stat.exceeded == 1
    assert single_stat.p50 == 5.0


def test_stats_edge_cases(tmp_path: Path) -> None:
    # Unreadable file or file with no functions
    unreadable = tmp_path / "bad.py"
    unreadable.write_bytes(b"\xff\xfe# invalid utf8")
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("# only comments\nx = 1\n")
    unsupported_file = tmp_path / "notes.txt"
    unsupported_file.write_text("hello\n")

    config = DesignConfig()
    stats = compute_stats(tmp_path, [unreadable, empty_file, unsupported_file], config)
    assert stats.by_language == {}

