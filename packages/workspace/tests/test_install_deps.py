"""
Unit tests for workspace_engine.cli.install_deps.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.cli import install_deps


def _completed(returncode: int, stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stderr = stderr
    return proc


def test_install_repo_deps_no_manifest_detected(tmp_path: Path) -> None:
    assert install_deps.install_repo_deps(tmp_path) is True


@pytest.mark.parametrize(
    ("files", "expected_cmd"),
    [
        (["yarn.lock"], ["yarn", "install"]),
        (["package-lock.json"], ["npm", "install"]),
        (["package.json"], ["npm", "install"]),
        (["gradlew"], ["./gradlew", "dependencies", "--quiet"]),
        (["pom.xml"], ["mvn", "dependency:resolve", "-q"]),
        (["go.mod"], ["go", "mod", "download"]),
        (["requirements.txt"], ["pip", "install", "-r", "requirements.txt"]),
        (["pyproject.toml"], ["pip", "install", "-e", "."]),
    ],
)
def test_install_repo_deps_detects_manifest_and_succeeds(
    tmp_path: Path, files: list[str], expected_cmd: list[str]
) -> None:
    for f in files:
        (tmp_path / f).write_text("", encoding="utf-8")

    with patch.object(install_deps.subprocess, "run", return_value=_completed(0)) as mock_run:
        assert install_deps.install_repo_deps(tmp_path) is True

    assert mock_run.call_args.args[0] == expected_cmd


def test_install_repo_deps_failure_logs_and_returns_false(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("", encoding="utf-8")
    with patch.object(install_deps.subprocess, "run", return_value=_completed(1, "boom" * 200)):
        assert install_deps.install_repo_deps(tmp_path) is False


def test_install_all_deps_missing_repositories_dir_and_not_git(tmp_path: Path) -> None:
    assert install_deps.install_all_deps(start_dir=tmp_path) == 1


def test_install_all_deps_single_repo_when_no_repositories_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with patch.object(install_deps, "install_repo_deps", return_value=True) as mock_install:
        assert install_deps.install_all_deps(start_dir=tmp_path) == 0
    mock_install.assert_called_once_with(tmp_path)


def test_install_all_deps_single_repo_failure(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with patch.object(install_deps, "install_repo_deps", return_value=False):
        assert install_deps.install_all_deps(start_dir=tmp_path) == 1


def test_install_all_deps_no_targets_found(tmp_path: Path) -> None:
    (tmp_path / "repositories").mkdir()
    assert install_deps.install_all_deps(start_dir=tmp_path) == 0


def test_install_all_deps_filters_by_repos_filter(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "a").mkdir()
    (repos_dir / "b").mkdir()

    with patch.object(install_deps, "install_repo_deps", return_value=True) as mock_install:
        result = install_deps.install_all_deps(repos_filter=["a"], start_dir=tmp_path)

    assert result == 0
    mock_install.assert_called_once_with(repos_dir / "a")


def test_install_all_deps_filter_reports_missing_repo(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()

    result = install_deps.install_all_deps(repos_filter=["missing"], start_dir=tmp_path)

    assert result == 0


def test_install_all_deps_processes_all_repos_and_reports_failure(tmp_path: Path) -> None:
    repos_dir = tmp_path / "repositories"
    repos_dir.mkdir()
    (repos_dir / "a").mkdir()
    (repos_dir / "b").mkdir()

    with patch.object(install_deps, "install_repo_deps", side_effect=[True, False]):
        result = install_deps.install_all_deps(start_dir=tmp_path)

    assert result == 1


def test_main_exits_with_install_all_deps_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["install-deps", "repo-a", "repo-b"])
    with (
        patch.object(install_deps, "install_all_deps", return_value=0) as mock_install,
        pytest.raises(SystemExit) as exc,
    ):
        install_deps.main()
    assert exc.value.code == 0
    mock_install.assert_called_once_with(repos_filter=["repo-a", "repo-b"])
