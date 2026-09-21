from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from spec.spec.trace import (
    Scenario,
    TraceabilityReport,
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
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_custom.py").write_text(
            "def test_custom_handler():\n    pass\n\ndef test_error_path():\n    pass\n",
            encoding="utf-8",
        )
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


def test_tasks_md_reference_without_test_file_does_not_credit_scenario():
    """A scenario mentioned in tasks.md or work.md without any test file MUST remain uncovered."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        feature_dir = root / ".spec" / "specs" / "my-feat"
        feature_dir.mkdir(parents=True)
        (feature_dir / "tasks.md").write_text(
            "# Tasks\n\n- [x] T-001 (@s1): Documented task without real test code\n",
            encoding="utf-8",
        )
        (feature_dir / "work.md").write_text(
            "# Work Log\n\n- @s1 -> test_nonexistent_function\n",
            encoding="utf-8",
        )

        scenarios = [
            Scenario(tag="@s1", title="Ghost scenario"),
        ]

        report = find_test_mappings(scenarios, root, feature_dir=feature_dir)
        assert report.total == 1
        assert report.covered_count == 0
        assert report.uncovered == ["@s1"]
        assert report.is_complete is False


def test_monorepo_package_test_discovery():
    """Tests located inside packages/*/tests/ are discovered in monorepo structures."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        pkg_test_dir = root / "packages" / "sub_pkg" / "tests"
        pkg_test_dir.mkdir(parents=True)
        (pkg_test_dir / "test_sub.py").write_text(
            "def test_feature_s1():\n    pass\n",
            encoding="utf-8",
        )

        scenarios = [
            Scenario(tag="@s1", title="Monorepo scenario"),
        ]

        report = find_test_mappings(scenarios, root)
        assert report.total == 1
        assert report.covered_count == 1
        assert "@s1" in report.covered
        assert report.is_complete is True


def test_empty_execution_output_uncovers_scenarios():
    """If verification checks ran but produced empty stdout/stderr, scenarios must NOT be credited."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_app.py").write_text(
            "def test_app_s1():\n    pass\n",
            encoding="utf-8",
        )
        scenarios = [
            Scenario(tag="@s1", title="App scenario"),
        ]

        class DummyCheck:
            evidence = {"stdout": "", "stderr": ""}

        report = find_test_mappings(scenarios, root, check_results=[DummyCheck()])
        assert report.total == 1
        assert report.covered_count == 0
        assert report.uncovered == ["@s1"]
        assert report.is_complete is False


def test_coverage_percent_is_full_when_there_are_no_scenarios():
    report = TraceabilityReport(feature="empty")
    assert report.coverage_percent == 100.0


def test_extract_scenarios_deduplicates_repeated_tags():
    content = (
        "@s1\nScenario: First mention\n  Given a\n  When b\n  Then c\n\n"
        "@s1\nScenario: Repeated tag is ignored\n  Given x\n  When y\n  Then z\n"
    )
    scenarios = extract_scenarios(content)
    assert len(scenarios) == 1
    assert scenarios[0].title == "First mention"


def test_find_test_mappings_returns_empty_report_for_no_scenarios():
    with tempfile.TemporaryDirectory() as temp_dir:
        report = find_test_mappings([], Path(temp_dir))
    assert report.total == 0
    assert report.uncovered == []


def test_monorepo_package_discovery_skips_non_directory_and_hidden_entries():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        packages_dir = root / "packages"
        packages_dir.mkdir()
        (packages_dir / "not_a_dir.txt").write_text("stray file", encoding="utf-8")
        (packages_dir / ".hidden").mkdir()
        (packages_dir / ".hidden" / "tests").mkdir(parents=True)

        scenarios = [Scenario(tag="@s1", title="Scenario")]
        report = find_test_mappings(scenarios, root)

        assert report.uncovered == ["@s1"]


def test_unreadable_test_file_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tests_dir = root / "tests"
        tests_dir.mkdir()
        broken = tests_dir / "test_broken.py"
        broken.write_text("def test_s1():\n    pass\n", encoding="utf-8")

        original_read_text = Path.read_text

        def failing_read_text(self: Path, *args: object, **kwargs: object) -> str:
            if self == broken:
                raise OSError("cannot read file")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", failing_read_text)

        scenarios = [Scenario(tag="@s1", title="Scenario")]
        report = find_test_mappings(scenarios, root)

        assert report.uncovered == ["@s1"]


def test_unreadable_work_log_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        feature_dir = root / ".spec" / "specs" / "my-feat"
        feature_dir.mkdir(parents=True)
        work_md = feature_dir / "work.md"
        work_md.write_text("- @s1 -> test_something\n", encoding="utf-8")

        original_read_text = Path.read_text

        def failing_read_text(self: Path, *args: object, **kwargs: object) -> str:
            if self == work_md:
                raise OSError("cannot read work log")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", failing_read_text)

        scenarios = [Scenario(tag="@s1", title="Scenario")]
        report = find_test_mappings(scenarios, root, feature_dir=feature_dir)

        assert report.uncovered == ["@s1"]


def _patch_alternating_scenario_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the per-scenario matcher in find_test_mappings match on the first
    call and miss on every later call for the same tag, so a duplicated tag can
    land in both `covered` and `uncovered` for the guard-branch tests below.
    """
    import re

    import spec.spec.trace as trace_module

    real_compile = re.compile
    calls = {"count": 0}

    class _NoMatch:
        def search(self, _text: str) -> None:
            return None

    def fake_compile(pattern: str, flags: int = 0):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compile(pattern, flags)
        return _NoMatch()

    monkeypatch.setattr(trace_module.re, "compile", fake_compile)


def test_check_results_zero_output_skips_tag_already_marked_uncovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_dup.py").write_text("def test_s1():\n    pass\n", encoding="utf-8")

        # Two scenario entries share the same tag. The per-scenario matcher is
        # patched to match on the first pass and miss on the second, so the tag
        # lands in both `covered` and `uncovered` before check_results is applied.
        scenarios = [
            Scenario(tag="@s1", title="First"),
            Scenario(tag="@s1", title="Second, forced uncovered"),
        ]

        _patch_alternating_scenario_match(monkeypatch)

        class DummyCheck:
            evidence: dict[str, str] = {"stdout": "", "stderr": ""}

        report = find_test_mappings(scenarios, root, check_results=[DummyCheck()])

        assert report.uncovered == ["@s1"]
        assert "@s1" not in report.covered


def test_check_results_with_output_skips_tag_already_marked_uncovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_dup.py").write_text("def test_s1():\n    pass\n", encoding="utf-8")

        scenarios = [
            Scenario(tag="@s1", title="First"),
            Scenario(tag="@s1", title="Second, forced uncovered"),
        ]

        _patch_alternating_scenario_match(monkeypatch)

        class DummyCheck:
            evidence = {"stdout": "unrelated output only", "stderr": ""}

        report = find_test_mappings(scenarios, root, check_results=[DummyCheck()])

        assert report.uncovered == ["@s1"]
        assert "@s1" not in report.covered
