"""
Unit tests for devscripts.sdd.constitution module — Project Constitution Management (Spec-Kit Aligned).
"""

from pathlib import Path
import tempfile
import pytest

from devscripts.sdd import constitution
from devscripts.adapters.bridge import get_sdd_core_rules


def test_write_and_read_constitution(tmp_path):
    cfile = constitution.write_constitution(
        target_dir=tmp_path,
        project_name="TestProject",
        description="Demo project for SDD",
        tech_stack="Python 3.14, Pytest, Oxlint",
        architecture_rules="- Strict SDD Lifecycle\n- Zero secrets in logs",
    )

    assert cfile.exists()
    assert cfile.name == "constitution.md"
    assert cfile.parent.name == "constitution"

    content = constitution.read_constitution(tmp_path)
    assert content is not None
    assert "TestProject" in content
    assert "Python 3.14, Pytest, Oxlint" in content
    assert "Strict SDD Lifecycle" in content


def test_constitution_embedded_in_sdd_core_rules(tmp_path):
    constitution.write_constitution(
        target_dir=tmp_path,
        project_name="EmbeddedDemo",
        description="Testing core rules embedding",
    )

    rules = get_sdd_core_rules(target_dir=str(tmp_path))
    assert "EmbeddedDemo" in rules
    assert "Constitución del Proyecto" in rules


def test_prompt_create_constitution(tmp_path, monkeypatch):
    inputs = iter(["MyInteractiveApp", "App description", "Node.js, Express", "- Clean Architecture"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cfile = constitution.prompt_create_constitution(target_dir=tmp_path)
    assert cfile.exists()

    content = cfile.read_text(encoding="utf-8")
    assert "MyInteractiveApp" in content
    assert "Node.js, Express" in content
    assert "- Clean Architecture" in content


def test_infer_project_constitution(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "auto-infer-pkg"\ndescription = "Auto inferred description"\ndependencies = ["pytest", "rich"]\n', encoding="utf-8")

    inferred = constitution.infer_project_constitution(tmp_path)
    assert inferred["project_name"] == "auto-infer-pkg"
    assert inferred["description"] == "Auto inferred description"
    assert "Python 3" in inferred["tech_stack"]
    assert "Pytest" in inferred["tech_stack"]

