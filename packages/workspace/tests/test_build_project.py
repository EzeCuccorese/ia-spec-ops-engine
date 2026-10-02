"""
Unit tests for workspace_engine.cli.build_project.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli import build_project


def test_build_project_no_recognized_manifest(tmp_path: Path) -> None:
    assert build_project.build_project(tmp_path) == 1


def test_build_project_maven(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    with (
        patch.object(build_project.set_java, "setups_java", return_value={"JAVA_HOME": "/jdk"}),
        patch.object(build_project, "run_command", return_value="build output") as mock_run,
    ):
        assert build_project.build_project(tmp_path) == 0
    build_call = mock_run.call_args_list[0]
    assert build_call.args[0] == "mvn clean install"


def test_build_project_gradlew(tmp_path: Path) -> None:
    (tmp_path / "gradlew").write_text("#!/bin/sh", encoding="utf-8")
    with (
        patch.object(build_project.set_java, "setups_java", return_value=None),
        patch.object(build_project, "run_command", return_value="") as mock_run,
    ):
        assert build_project.build_project(tmp_path) == 0
    # No java env available -> falls back to a copy of the current environment.
    build_call = mock_run.call_args_list[0]
    assert build_call.args[0] == "./gradlew clean build -x test"
    assert build_call.kwargs["env"] is not None


def test_build_project_gradle_groovy(tmp_path: Path) -> None:
    (tmp_path / "build.gradle").write_text("", encoding="utf-8")
    with (
        patch.object(build_project.set_java, "setups_java", return_value={"JAVA_HOME": "/jdk"}),
        patch.object(build_project, "run_command", return_value=None),
    ):
        assert build_project.build_project(tmp_path) == 0


def test_build_project_gradle_kts(tmp_path: Path) -> None:
    (tmp_path / "build.gradle.kts").write_text("", encoding="utf-8")
    with (
        patch.object(build_project.set_java, "setups_java", return_value={"JAVA_HOME": "/jdk"}),
        patch.object(build_project, "run_command", return_value=None),
    ):
        assert build_project.build_project(tmp_path) == 0


@pytest.mark.parametrize(
    ("manifest", "content", "command"),
    [
        ("package.json", '{"scripts": {"build": "x"}}', "npm run build"),
        ("package.json", '{"scripts": {}}', "npm test"),
        ("go.mod", "module x", "go build ./..."),
        ("Cargo.toml", "[package]", "cargo build"),
        ("pyproject.toml", "[project]", "python3 -m pip install -e ."),
    ],
    ids=["npm-build-script", "npm-no-build-script", "go", "cargo", "python"],
)
def test_build_project_runs_the_ecosystem_command(
    tmp_path: Path, manifest: str, content: str, command: str
) -> None:
    (tmp_path / manifest).write_text(content, encoding="utf-8")
    with patch.object(build_project, "run_command", return_value=None) as mock_run:
        assert build_project.build_project(tmp_path) == 0
    assert mock_run.call_args_list[0].args[0] == command


def test_build_project_build_failure_returns_1(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x", encoding="utf-8")
    with patch.object(build_project, "run_command", side_effect=subprocess.SubprocessError("boom")):
        assert build_project.build_project(tmp_path) == 1


def test_build_project_build_failure_oserror(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x", encoding="utf-8")
    with patch.object(build_project, "run_command", side_effect=OSError("boom")):
        assert build_project.build_project(tmp_path) == 1


def test_build_project_version_command_prints_when_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "go.mod").write_text("module x", encoding="utf-8")
    with patch.object(build_project, "run_command", side_effect=["build ok", "v1.2.3"]):
        assert build_project.build_project(tmp_path) == 0
    captured = capsys.readouterr()
    assert "build ok" in captured.out


def test_build_project_version_command_failure_is_swallowed(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x", encoding="utf-8")
    with patch.object(
        build_project,
        "run_command",
        side_effect=["", subprocess.SubprocessError("boom")],
    ):
        assert build_project.build_project(tmp_path) == 0


def test_build_project_version_command_oserror_is_swallowed(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x", encoding="utf-8")
    with patch.object(build_project, "run_command", side_effect=["", OSError("boom")]):
        assert build_project.build_project(tmp_path) == 0


def test_build_project_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert build_project.build_project() == 1


def test_main_exits_with_build_project_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(build_project, "build_project", lambda d: calls.append(d) or 3)
    with pytest.raises(SystemExit) as exc:
        build_project.main([str(tmp_path)])
    assert exc.value.code == 3
    assert calls == [tmp_path.resolve()]
