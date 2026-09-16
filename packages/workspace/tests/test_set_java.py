"""
Tests for workspace_engine.cli.set_java (Java version detection and SDKMAN parsing).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from workspace_engine.cli.set_java import (
    detect_required_java_version,
    find_best_java_match,
    get_current_java_version,
    get_java_env,
)


def test_detect_required_java_version_from_pom(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(
        "<project><properties><maven.compiler.target>17</maven.compiler.target>"
        "</properties></project>",
        encoding="utf-8",
    )
    assert detect_required_java_version(tmp_path) == "17"


def test_detect_required_java_version_from_pom_java_version_tag(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(
        "<project><properties><java.version>21</java.version></properties></project>",
        encoding="utf-8",
    )
    assert detect_required_java_version(tmp_path) == "21"


def test_detect_required_java_version_from_gradle_kts(tmp_path: Path) -> None:
    gradle_kts = tmp_path / "build.gradle.kts"
    gradle_kts.write_text(
        "java { toolchain { languageVersion.set(JavaLanguageVersion.of(11)) } }",
        encoding="utf-8",
    )
    assert detect_required_java_version(tmp_path) == "11"


def test_detect_required_java_version_from_gradle_source_compatibility(tmp_path: Path) -> None:
    gradle = tmp_path / "build.gradle"
    gradle.write_text("sourceCompatibility = '1.8'", encoding="utf-8")
    assert detect_required_java_version(tmp_path) == "1.8"


def test_detect_required_java_version_none(tmp_path: Path) -> None:
    assert detect_required_java_version(tmp_path) is None


def test_get_current_java_version_parses_stderr() -> None:
    fake_result = subprocess.CompletedProcess(
        args=["java", "-version"],
        returncode=0,
        stdout="",
        stderr='openjdk version "17.0.2" 2022-01-18\n',
    )
    with patch("subprocess.run", return_value=fake_result):
        assert get_current_java_version() == "17.0.2"


def test_get_current_java_version_no_match() -> None:
    fake_result = subprocess.CompletedProcess(
        args=["java", "-version"], returncode=0, stdout="garbage", stderr=""
    )
    with patch("subprocess.run", return_value=fake_result):
        assert get_current_java_version() is None


def test_get_current_java_version_handles_missing_binary() -> None:
    with patch("subprocess.run", side_effect=OSError("java not found")):
        assert get_current_java_version() is None


def test_find_best_java_match_no_sdkman(tmp_path: Path) -> None:
    with patch("os.path.expanduser", return_value=str(tmp_path / "nope.sh")):
        assert find_best_java_match("17") is None


def test_find_best_java_match_parses_table(tmp_path: Path) -> None:
    sdkman_init = tmp_path / "sdkman-init.sh"
    sdkman_init.write_text("", encoding="utf-8")
    table = (
        "Vendor  | Use | Version | Dist    | Status    | Identifier\n"
        "Temurin |     | 17.0.2  | tem     | installed | 17.0.2-tem\n"
    )
    with (
        patch("os.path.expanduser", return_value=str(sdkman_init)),
        patch("workspace_engine.cli.set_java.run_command", return_value=table) as mock_run,
    ):
        result = find_best_java_match("17.0.2")
    assert result == "17.0.2-tem"
    # Ensures no shell=True is used: run_command is invoked with an argv list.
    args, kwargs = mock_run.call_args
    assert isinstance(args[0], list)
    assert args[0][0] == "bash"
    assert "shell" not in kwargs


def test_find_best_java_match_empty_output(tmp_path: Path) -> None:
    sdkman_init = tmp_path / "sdkman-init.sh"
    sdkman_init.write_text("", encoding="utf-8")
    with (
        patch("os.path.expanduser", return_value=str(sdkman_init)),
        patch("workspace_engine.cli.set_java.run_command", return_value=None),
    ):
        assert find_best_java_match("17") is None


def test_get_java_env_no_sdkman(tmp_path: Path) -> None:
    with patch("os.path.expanduser", return_value=str(tmp_path / "nope.sh")):
        assert get_java_env("17.0.2-tem") is None


def test_get_java_env_parses_output(tmp_path: Path) -> None:
    sdkman_init = tmp_path / "sdkman-init.sh"
    sdkman_init.write_text("", encoding="utf-8")
    output = "JAVA_HOME=/opt/java/17\nPATH=/opt/java/17/bin:/usr/bin"
    with (
        patch("os.path.expanduser", return_value=str(sdkman_init)),
        patch("workspace_engine.cli.set_java.run_command", return_value=output) as mock_run,
    ):
        env = get_java_env("17.0.2-tem")
    assert env == {"JAVA_HOME": "/opt/java/17", "PATH": "/opt/java/17/bin:/usr/bin"}
    args, kwargs = mock_run.call_args
    assert isinstance(args[0], list)
    assert args[0][0] == "bash"
    assert "shell" not in kwargs
