"""
Unit tests for workspace_engine.cli.unit_test_benchmark.

`run_final` (from services.benchmark_display) is patched out in every test —
that module is covered separately and is not in scope here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.cli import unit_test_benchmark


def _completed(returncode: int) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    return proc


def test_run_repo_tests_no_recognized_suite(tmp_path: Path) -> None:
    result = unit_test_benchmark.run_repo_tests(tmp_path)
    assert result["status"] == "no_tests"
    assert result["exit_code"] == 0


@pytest.mark.parametrize(
    ("marker_file", "expected_cmd"),
    [
        ("yarn.lock", ["yarn", "test", "--passWithNoTests"]),
        ("package.json", ["npm", "test", "--", "--passWithNoTests"]),
        ("go.mod", ["go", "test", "./..."]),
        ("pyproject.toml", ["pytest", "-q"]),
        ("pytest.ini", ["pytest", "-q"]),
    ],
)
def test_run_repo_tests_success_for_stacks_without_java(
    tmp_path: Path, marker_file: str, expected_cmd: list[str]
) -> None:
    (tmp_path / marker_file).write_text("", encoding="utf-8")
    with patch.object(
        unit_test_benchmark.subprocess, "run", return_value=_completed(0)
    ) as mock_run:
        result = unit_test_benchmark.run_repo_tests(tmp_path)

    assert mock_run.call_args.args[0] == expected_cmd
    assert result["status"] == "green"
    assert result["exit_code"] == 0


def test_run_repo_tests_gradlew_with_java_env(tmp_path: Path) -> None:
    (tmp_path / "gradlew").write_text("", encoding="utf-8")
    with (
        patch.object(
            unit_test_benchmark.set_java, "setups_java", return_value={"JAVA_HOME": "/jdk"}
        ),
        patch.object(unit_test_benchmark.subprocess, "run", return_value=_completed(0)) as mock_run,
    ):
        result = unit_test_benchmark.run_repo_tests(tmp_path)

    assert mock_run.call_args.args[0] == ["./gradlew", "test", "--quiet", "--no-daemon"]
    assert mock_run.call_args.kwargs["env"]["JAVA_HOME"] == "/jdk"
    assert result["status"] == "green"


def test_run_repo_tests_gradlew_without_java_env(tmp_path: Path) -> None:
    (tmp_path / "gradlew").write_text("", encoding="utf-8")
    with (
        patch.object(unit_test_benchmark.set_java, "setups_java", return_value=None),
        patch.object(unit_test_benchmark.subprocess, "run", return_value=_completed(0)),
    ):
        result = unit_test_benchmark.run_repo_tests(tmp_path)
    assert result["status"] == "green"


def test_run_repo_tests_maven_with_java_env(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    with (
        patch.object(
            unit_test_benchmark.set_java, "setups_java", return_value={"JAVA_HOME": "/jdk"}
        ),
        patch.object(unit_test_benchmark.subprocess, "run", return_value=_completed(0)) as mock_run,
    ):
        result = unit_test_benchmark.run_repo_tests(tmp_path)

    assert mock_run.call_args.args[0] == ["mvn", "test", "-q"]
    assert mock_run.call_args.kwargs["env"]["JAVA_HOME"] == "/jdk"
    assert result["status"] == "green"


def test_run_repo_tests_maven_failure(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    with (
        patch.object(unit_test_benchmark.set_java, "setups_java", return_value=None),
        patch.object(unit_test_benchmark.subprocess, "run", return_value=_completed(1)),
    ):
        result = unit_test_benchmark.run_repo_tests(tmp_path)
    assert result["status"] == "red_infra"
    assert result["exit_code"] == 1


def test_run_benchmark_no_repositories_dir_and_not_git(tmp_path: Path) -> None:
    with patch.object(unit_test_benchmark, "run_final"):
        result = unit_test_benchmark.run_benchmark(start_dir=tmp_path)
    assert result == 1


def test_run_benchmark_single_repo_when_no_repositories_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with (
        patch.object(unit_test_benchmark, "run_repo_tests") as mock_run_repo,
        patch.object(unit_test_benchmark, "run_final") as mock_run_final,
    ):
        mock_run_repo.return_value = {
            "repo": tmp_path.name,
            "exit_code": 0,
            "status": "green",
            "cold_secs": "1.0",
        }
        result = unit_test_benchmark.run_benchmark(start_dir=tmp_path)

    assert result == 0
    mock_run_final.assert_called_once()
    summary_file = tmp_path / ".ai-toolkit" / "unit-test-benchmark" / "summary.tsv"
    assert summary_file.is_file()


def test_run_benchmark_no_targets_found(tmp_path: Path) -> None:
    (tmp_path / "repositories").mkdir()
    with patch.object(unit_test_benchmark, "run_final") as mock_run_final:
        result = unit_test_benchmark.run_benchmark(start_dir=tmp_path)
    assert result == 0
    mock_run_final.assert_not_called()


def test_run_benchmark_filters_by_repos_filter(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "a").mkdir()
    (repos_dir / "b").mkdir()

    with (
        patch.object(unit_test_benchmark, "run_repo_tests") as mock_run_repo,
        patch.object(unit_test_benchmark, "run_final"),
    ):
        mock_run_repo.return_value = {
            "repo": "a",
            "exit_code": 0,
            "status": "green",
            "cold_secs": "0.10",
        }
        result = unit_test_benchmark.run_benchmark(repos_filter=["a"], start_dir=tmp_path)

    assert result == 0
    mock_run_repo.assert_called_once_with(repos_dir / "a")


def test_run_benchmark_processes_all_repos_and_reports_failures(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "a").mkdir()
    (repos_dir / "b").mkdir()

    def fake_run_repo_tests(repo_path: Path) -> dict:
        ok = repo_path.name == "a"
        return {
            "repo": repo_path.name,
            "exit_code": 0 if ok else 1,
            "status": "green" if ok else "red_infra",
            "cold_secs": "0.10",
        }

    with (
        patch.object(unit_test_benchmark, "run_repo_tests", side_effect=fake_run_repo_tests),
        patch.object(unit_test_benchmark, "run_final") as mock_run_final,
    ):
        result = unit_test_benchmark.run_benchmark(start_dir=tmp_path)

    assert result == 1
    mock_run_final.assert_called_once()
    summary_file = repos_dir.parent / ".ai-toolkit" / "unit-test-benchmark" / "summary.tsv"
    content = summary_file.read_text(encoding="utf-8")
    assert "a" in content and "b" in content


def test_main_exits_with_run_benchmark_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["benchmark", "repo-a"])
    with (
        patch.object(unit_test_benchmark, "run_benchmark", return_value=0) as mock_bench,
        pytest.raises(SystemExit) as exc,
    ):
        unit_test_benchmark.main()
    assert exc.value.code == 0
    mock_bench.assert_called_once_with(repos_filter=["repo-a"])
