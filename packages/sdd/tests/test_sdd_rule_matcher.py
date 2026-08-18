"""
Tests unitarios para el motor de Dynamic Rule Matcher y Context Budgeting.
"""

from pathlib import Path
import pytest

from sdd_engine.core.rule_matcher import match_rules_for_files
from sdd_engine.adapters.bridge import RuleDefinition


def test_rule_matcher_empty_files(tmp_path: Path):
    rules_dir = tmp_path / "rules"
    (rules_dir / "global").mkdir(parents=True)
    (rules_dir / "scoped").mkdir(parents=True)

    (rules_dir / "global" / "01-test.md").write_text("---\nname: global-1\n---\nGlobal Rule Body\n")
    (rules_dir / "scoped" / "python.md").write_text("---\nname: python-rule\nglobs: ['*.py']\n---\nPython Scoped Body\n")

    res = match_rules_for_files(target_files=[], target_dir=tmp_path)
    assert len(res.global_rules) == 1
    assert len(res.matched_scoped_rules) == 0
    assert len(res.unmatched_scoped_rules) == 1
    assert res.savings_percentage > 0


def test_rule_matcher_matches_python_files(tmp_path: Path):
    rules_dir = tmp_path / "rules"
    (rules_dir / "global").mkdir(parents=True)
    (rules_dir / "scoped").mkdir(parents=True)

    (rules_dir / "global" / "01-test.md").write_text("---\nname: global-1\n---\nGlobal Rule Body\n")
    (rules_dir / "scoped" / "python.md").write_text("---\nname: python-rule\nglobs: ['**/*.py', 'pyproject.toml']\n---\nPython Scoped Body\n")
    (rules_dir / "scoped" / "react.md").write_text("---\nname: react-rule\nglobs: ['**/*.tsx', '**/*.jsx']\n---\nReact Scoped Body\n")

    res = match_rules_for_files(target_files=["src/main.py"], target_dir=tmp_path)
    assert len(res.global_rules) == 1
    assert len(res.matched_scoped_rules) == 1
    assert res.matched_scoped_rules[0].name == "python-rule"
    assert len(res.unmatched_scoped_rules) == 1
    assert res.unmatched_scoped_rules[0].name == "react-rule"

    rendered = res.render_context()
    assert "Global Rule Body" in rendered
    assert "Python Scoped Body" in rendered
    assert "React Scoped Body" not in rendered
