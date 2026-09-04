from __future__ import annotations

import tempfile
from pathlib import Path

from spec.spec.trace import (
    Scenario,
    extract_scenarios,
    find_test_mappings,
)


def test_extract_scenarios():
    content = """# Spec: User Authentication

## Acceptance Criteria
@s1
Scenario: Successful login with valid credentials
  Given a registered user
  When credentials are valid
  Then status code is 200

@s2
Escenario: Invalid password returns 401
  Given a registered user
  When password is wrong
  Then status code is 401
"""
    scenarios = extract_scenarios(content)
    assert len(scenarios) == 2
    assert scenarios[0] == Scenario(tag="@s1", title="Successful login with valid credentials")
    assert scenarios[1] == Scenario(tag="@s2", title="Invalid password returns 401")


def test_find_test_mappings_covered_and_uncovered():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text(
            "def test_login_s1():\n    pass\n",
            encoding="utf-8",
        )

        scenarios = [
            Scenario(tag="@s1", title="Login success"),
            Scenario(tag="@s2", title="Login fail"),
        ]

        report = find_test_mappings(scenarios, root)
        assert report.total == 2
        assert report.covered_count == 1
        assert "@s1" in report.covered
        assert "@s2" in report.uncovered
        assert report.is_complete is False
        assert report.coverage_percent == 50.0


def test_find_test_mappings_via_work_log():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        feature_dir = root / ".spec" / "specs" / "my-feat"
        feature_dir.mkdir(parents=True)
        (feature_dir / "work.md").write_text(
            "# Work Log\n\n- @s1 -> test_custom_handler\n- @s2 -> test_error_path\n",
            encoding="utf-8",
        )

        scenarios = [
            Scenario(tag="@s1", title="Custom handler"),
            Scenario(tag="@s2", title="Error path"),
        ]

        report = find_test_mappings(scenarios, root, feature_dir=feature_dir)
        assert report.total == 2
        assert report.covered_count == 2
        assert report.is_complete is True
        assert report.coverage_percent == 100.0
