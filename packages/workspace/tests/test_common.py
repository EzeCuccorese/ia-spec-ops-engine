"""
Tests para utilidades compartidas de workspace_engine.common (colores, frontmatter, dotenv, project, subprocess).
"""

from enum import Enum
from pathlib import Path

import pytest
from workspace_engine.common import (
    Color,
    ProjectType,
    colorize,
    parse_dotenv,
    parse_frontmatter,
    run_command_safe,
)
from workspace_engine.common import project as project_mod
from workspace_engine.common.process import get_process_cmdline


def test_colorize():
    res = colorize("hello", Color.GREEN)
    assert Color.GREEN in res
    assert Color.RESET in res
    assert "hello" in res


def test_parse_frontmatter_valid():
    content = """---
name: my-rule
description: Test Rule Description
globs: ["*.py", "*.ts"]
alwaysApply: true
---

# Content Body
Here is the markdown.
"""
    meta, body = parse_frontmatter(content)
    assert meta["name"] == "my-rule"
    assert meta["description"] == "Test Rule Description"
    assert meta["globs"] == ["*.py", "*.ts"]
    assert meta["alwaysApply"] is True
    assert "# Content Body" in body


def test_run_command_safe_echo():
    code, stdout, stderr = run_command_safe(["echo", "workspace"])
    assert code == 0
    assert "workspace" in stdout


def test_run_command_safe_timeout():
    # Timeout corto simulado
    code, stdout, stderr = run_command_safe(["sleep", "2"], timeout=1)
    assert code == 124
    assert "TimeoutExpired" in stderr


def test_project_type_str_enum_compatibility():
    for member in ProjectType:
        assert isinstance(member, str)
        assert isinstance(member, Enum)
        assert isinstance(member.value, str)
        assert str(member) == member.value
        assert f"{member}" == member.value

    assert isinstance(ProjectType.PYTHON, str)
    assert isinstance(ProjectType.PYTHON, Enum)
    assert ProjectType.PYTHON == "python"
    assert ProjectType.PYTHON.value == "python"
    assert str(ProjectType.PYTHON) == "python"
    assert issubclass(ProjectType, (str, Enum))


def test_project_type_str_enum_fallback_python_310():
    import importlib
    from unittest.mock import patch

    with patch("sys.version_info", (3, 10, 0, "final", 0)):
        import workspace_engine.common.project as proj_mod

        importlib.reload(proj_mod)
        try:
            assert issubclass(proj_mod.StrEnum, (str, Enum))
            for member in proj_mod.ProjectType:
                assert isinstance(member, str)
                assert isinstance(member, Enum)
                assert str(member) == member.value
                assert f"{member}" == member.value

            assert proj_mod.ProjectType.PYTHON == "python"
            assert proj_mod.ProjectType.PYTHON.value == "python"
            assert str(proj_mod.ProjectType.PYTHON) == "python"
            assert f"{proj_mod.ProjectType.PYTHON}" == "python"
        finally:
            importlib.reload(proj_mod)


def test_find_project_root_finds_git_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert project_mod.find_project_root(nested) == tmp_path


def test_find_project_root_finds_specify_dir(tmp_path: Path) -> None:
    (tmp_path / ".specify").mkdir()
    assert project_mod.find_project_root(tmp_path) == tmp_path


def test_find_project_root_finds_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    assert project_mod.find_project_root(tmp_path) == tmp_path


def test_find_project_root_no_markers_returns_start(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    # No .git/.specify/pyproject.toml anywhere up the chain within tmp_path.
    result = project_mod.find_project_root(isolated)
    assert isolated in (result, *result.parents) or result == isolated


def test_read_package_json_missing(tmp_path: Path) -> None:
    assert project_mod.read_package_json(tmp_path) is None


def test_read_package_json_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not valid json", encoding="utf-8")
    assert project_mod.read_package_json(tmp_path) is None


def test_read_package_json_valid(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "pkg"}', encoding="utf-8")
    assert project_mod.read_package_json(tmp_path) == {"name": "pkg"}


def test_is_spring_boot_app_properties(tmp_path: Path) -> None:
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.properties").write_text("", encoding="utf-8")
    assert project_mod.is_spring_boot_app(tmp_path) is True


def test_is_spring_boot_app_yml(tmp_path: Path) -> None:
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text("", encoding="utf-8")
    assert project_mod.is_spring_boot_app(tmp_path) is True


def test_is_spring_boot_app_yaml(tmp_path: Path) -> None:
    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yaml").write_text("", encoding="utf-8")
    assert project_mod.is_spring_boot_app(tmp_path) is True


def test_is_spring_boot_app_false(tmp_path: Path) -> None:
    assert project_mod.is_spring_boot_app(tmp_path) is False


def test_is_kotlin_service_gradle_kts(tmp_path: Path) -> None:
    (tmp_path / "build.gradle.kts").write_text("", encoding="utf-8")
    assert project_mod.is_kotlin_service(tmp_path) is True


def test_is_kotlin_service_settings_gradle_kts(tmp_path: Path) -> None:
    (tmp_path / "settings.gradle.kts").write_text("", encoding="utf-8")
    assert project_mod.is_kotlin_service(tmp_path) is True


def test_is_kotlin_service_by_source_glob(tmp_path: Path) -> None:
    src = tmp_path / "src" / "main" / "kotlin" / "com" / "example"
    src.mkdir(parents=True)
    (src / "Main.kt").write_text("", encoding="utf-8")
    assert project_mod.is_kotlin_service(tmp_path) is True


def test_is_kotlin_service_false(tmp_path: Path) -> None:
    assert project_mod.is_kotlin_service(tmp_path) is False


def test_is_go_service(tmp_path: Path) -> None:
    assert project_mod.is_go_service(tmp_path) is False
    (tmp_path / "go.mod").write_text("", encoding="utf-8")
    assert project_mod.is_go_service(tmp_path) is True


def test_is_rust_service(tmp_path: Path) -> None:
    assert project_mod.is_rust_service(tmp_path) is False
    (tmp_path / "Cargo.toml").write_text("", encoding="utf-8")
    assert project_mod.is_rust_service(tmp_path) is True


def test_is_bun_project_lockb(tmp_path: Path) -> None:
    (tmp_path / "bun.lockb").write_text("", encoding="utf-8")
    assert project_mod.is_bun_project(tmp_path) is True


def test_is_bun_project_lock(tmp_path: Path) -> None:
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")
    assert project_mod.is_bun_project(tmp_path) is True


def test_is_bun_project_bunfig(tmp_path: Path) -> None:
    (tmp_path / "bunfig.toml").write_text("", encoding="utf-8")
    assert project_mod.is_bun_project(tmp_path) is True


def test_is_bun_project_false(tmp_path: Path) -> None:
    assert project_mod.is_bun_project(tmp_path) is False


def test_detect_fe_framework_astro_config(tmp_path: Path) -> None:
    (tmp_path / "astro.config.mjs").write_text("", encoding="utf-8")
    assert project_mod.detect_fe_framework(tmp_path) == "astro"


def test_detect_fe_framework_astro_config_ts(tmp_path: Path) -> None:
    (tmp_path / "astro.config.ts").write_text("", encoding="utf-8")
    assert project_mod.detect_fe_framework(tmp_path) == "astro"


def test_detect_fe_framework_svelte_config(tmp_path: Path) -> None:
    (tmp_path / "svelte.config.js").write_text("", encoding="utf-8")
    assert project_mod.detect_fe_framework(tmp_path) == "svelte"


def test_detect_fe_framework_no_package_json(tmp_path: Path) -> None:
    assert project_mod.detect_fe_framework(tmp_path) is None


@pytest.mark.parametrize(
    ("deps", "expected"),
    [
        ({"astro": "1.0"}, "astro"),
        ({"svelte": "1.0"}, "svelte"),
        ({"@sveltejs/kit": "1.0"}, "svelte"),
        ({"next": "1.0"}, "next"),
        ({"react": "1.0"}, "react"),
        ({"react-dom": "1.0"}, "react"),
        ({"vue": "1.0"}, "vue"),
        ({"@angular/core": "1.0"}, "angular"),
        ({"vite": "1.0"}, "vite"),
        ({"some-other-lib": "1.0"}, "node"),
    ],
)
def test_detect_fe_framework_from_dependencies(tmp_path: Path, deps: dict, expected: str) -> None:
    import json

    (tmp_path / "package.json").write_text(json.dumps({"dependencies": deps}), encoding="utf-8")
    assert project_mod.detect_fe_framework(tmp_path) == expected


def test_detect_fe_framework_from_dev_dependencies(tmp_path: Path) -> None:
    import json

    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"vite": "1.0"}}), encoding="utf-8"
    )
    assert project_mod.detect_fe_framework(tmp_path) == "vite"


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (
            lambda p: (
                (p / "src" / "main" / "resources").mkdir(parents=True)
                or (p / "src" / "main" / "resources" / "application.yml").write_text(
                    "", encoding="utf-8"
                )
            ),
            project_mod.ProjectType.SPRING_BOOT,
        ),
        (
            lambda p: (p / "build.gradle.kts").write_text("", encoding="utf-8"),
            project_mod.ProjectType.KOTLIN,
        ),
        (
            lambda p: (p / "gradlew").write_text("", encoding="utf-8"),
            project_mod.ProjectType.GRADLE,
        ),
        (
            lambda p: (p / "build.gradle").write_text("", encoding="utf-8"),
            project_mod.ProjectType.GRADLE,
        ),
        (lambda p: (p / "pom.xml").write_text("", encoding="utf-8"), project_mod.ProjectType.MAVEN),
        (lambda p: (p / "go.mod").write_text("", encoding="utf-8"), project_mod.ProjectType.GO),
        (
            lambda p: (p / "Cargo.toml").write_text("", encoding="utf-8"),
            project_mod.ProjectType.RUST,
        ),
        (lambda p: (p / "bun.lockb").write_text("", encoding="utf-8"), project_mod.ProjectType.BUN),
        (
            lambda p: (p / "package.json").write_text("{}", encoding="utf-8"),
            project_mod.ProjectType.NODE,
        ),
        (
            lambda p: (p / "pyproject.toml").write_text("", encoding="utf-8"),
            project_mod.ProjectType.PYTHON,
        ),
        (
            lambda p: (p / "requirements.txt").write_text("", encoding="utf-8"),
            project_mod.ProjectType.PYTHON,
        ),
        (
            lambda p: (p / "setup.py").write_text("", encoding="utf-8"),
            project_mod.ProjectType.PYTHON,
        ),
        (lambda _p: None, project_mod.ProjectType.UNKNOWN),
    ],
)
def test_detect_project_type(tmp_path: Path, setup, expected) -> None:
    setup(tmp_path)
    assert project_mod.detect_project_type(tmp_path) == expected


def test_get_process_cmdline_invalid_pid_returns_empty() -> None:
    assert get_process_cmdline(0) == ""
    assert get_process_cmdline(1) == ""


def test_get_process_cmdline_via_ps() -> None:
    import os

    result = get_process_cmdline(os.getpid())
    assert isinstance(result, str)


def test_get_process_cmdline_ps_nonzero_returncode(monkeypatch) -> None:
    from workspace_engine.common import process as process_mod

    def fake_run(*_args, **_kwargs):
        return process_mod.subprocess.CompletedProcess(args=[], returncode=1, stdout="")

    monkeypatch.setattr(process_mod.subprocess, "run", fake_run)
    assert get_process_cmdline(999999) == ""


def test_get_process_cmdline_ps_raises_subprocess_error(monkeypatch) -> None:
    from workspace_engine.common import process as process_mod

    def raise_subprocess_error(*_args, **_kwargs):
        raise process_mod.subprocess.SubprocessError("boom")

    monkeypatch.setattr(process_mod.subprocess, "run", raise_subprocess_error)
    assert get_process_cmdline(999999) == ""


def test_get_process_cmdline_unreadable_proc_falls_back_to_ps(monkeypatch) -> None:
    import os

    from workspace_engine.common import process as process_mod

    class BrokenPath:
        def exists(self) -> bool:
            return True

        def read_text(self, encoding: str = "utf-8") -> str:
            raise OSError("cannot read")

    def fake_path(value: str):
        if value == f"/proc/{os.getpid()}/cmdline":
            return BrokenPath()
        return Path(value)

    monkeypatch.setattr(process_mod, "Path", fake_path)
    result = get_process_cmdline(os.getpid())
    assert isinstance(result, str)


def test_parse_dotenv_missing_file(tmp_path: Path) -> None:
    assert parse_dotenv(tmp_path / "missing.env") == {}


def test_parse_dotenv_unreadable_file(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\n", encoding="utf-8")

    def raise_os_error(self, encoding="utf-8", errors="ignore"):
        raise OSError("unreadable")

    monkeypatch.setattr(Path, "read_text", raise_os_error)
    assert parse_dotenv(target) == {}


def test_parse_dotenv_line_without_equals(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=1\nNOT_A_VAR_LINE\nB=2\n", encoding="utf-8")
    result = parse_dotenv(target)
    assert result == {"A": "1", "B": "2"}


def test_parse_dotenv_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("\n# a comment\nexport A=1\n", encoding="utf-8")
    result = parse_dotenv(target)
    assert result == {"A": "1"}


def test_parse_dotenv_strips_surrounding_quotes(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("A=\"hello\"\nB='world'\n", encoding="utf-8")
    result = parse_dotenv(target)
    assert result == {"A": "hello", "B": "world"}


def test_parse_frontmatter_no_leading_delimiter() -> None:
    meta, body = parse_frontmatter("# Just a title\nBody text")
    assert meta == {}
    assert body == "# Just a title\nBody text"


def test_parse_frontmatter_incomplete_delimiters() -> None:
    meta, body = parse_frontmatter("---\nonly one delimiter")
    assert meta == {}


def test_parse_frontmatter_line_without_colon() -> None:
    content = "---\nno_colon_here\nname: value\n---\nBody"
    meta, body = parse_frontmatter(content)
    assert meta == {"name": "value"}


def test_parse_frontmatter_invalid_json_list_fallback() -> None:
    content = "---\ntags: [a, b, c]\n---\nBody"
    meta, _body = parse_frontmatter(content)
    assert meta["tags"] == ["a", "b", "c"]


def test_parse_frontmatter_false_and_no_values() -> None:
    content = "---\nflag_false: false\nflag_no: no\n---\nBody"
    meta, _body = parse_frontmatter(content)
    assert meta["flag_false"] is False
    assert meta["flag_no"] is False
