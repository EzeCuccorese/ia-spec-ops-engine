"""
Tests para utilidades compartidas de workspace_engine.common (colores, frontmatter, dotenv, project, subprocess).
"""

from workspace_engine.common import (
    Color,
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
