"""
Tests para utilidades compartidas de workspace_engine.common (colores, frontmatter, dotenv, project, subprocess).
"""

from enum import Enum

from workspace_engine.common import (
    Color,
    ProjectType,
    colorize,
    parse_frontmatter,
    run_command_safe,
)


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
    code, stdout, stderr = run_command_safe(["echo", "specops"])
    assert code == 0
    assert "specops" in stdout


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
