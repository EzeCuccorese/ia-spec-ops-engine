from __future__ import annotations

import tempfile
from pathlib import Path

import spec.spec.assist as assist_module
from spec.governance.project import ProjectGovernance
from spec.spec.assist import TestAssistant
from spec.spec.trace import TraceabilityReport
from spec.spec.workflow import Workflow


def test_assist_idle_repository():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ctx = TestAssistant(root).inspect()
        assert ctx.stage == "idle"
        assert ctx.next_scenario is None
        assert "No active specification" in ctx.actionable_instruction


def test_assist_with_uncovered_scenario():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("Login Feature", "User authentication")
        spec_md = workflow.feature_dir("login-feature") / "spec.md"
        spec_md.write_text(
            "# Spec: Login Feature\n\n"
            "@s1\nScenario: Valid password logs in\n  Given a user\n  When password matches\n  Then 200\n\n"
            "@s2\nScenario: Invalid password fails\n  Given a user\n  When password wrong\n  Then 401\n",
            encoding="utf-8",
        )
        workflow.create_plan()
        workflow.create_tasks()
        workflow.begin_work()

        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text(
            "def test_login_s1():\n    pass\n", encoding="utf-8"
        )

        # @s1 is covered by test_login_s1, so @s2 should be next!
        ctx = TestAssistant(root).inspect()
        assert ctx.feature == "login-feature"
        assert ctx.stage == "work"
        assert ctx.total_scenarios == 2
        assert ctx.next_scenario is not None
        assert ctx.next_scenario.tag == "@s2"
        assert "@s2" in ctx.actionable_instruction


def test_assist_all_scenarios_covered():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("Login Feature", "User authentication")
        spec_md = workflow.feature_dir("login-feature") / "spec.md"
        spec_md.write_text(
            "# Spec: Login Feature\n\n"
            "@s1\nScenario: Valid password logs in\n  Given a user\n  When password matches\n  Then 200\n",
            encoding="utf-8",
        )
        workflow.create_plan()
        workflow.create_tasks()
        workflow.begin_work()

        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_auth.py").write_text(
            "def test_login_success():\n    pass\n", encoding="utf-8"
        )

        work_md = workflow.feature_dir("login-feature") / "work.md"
        work_md.write_text("# Work Log\n\n- @s1 -> test_login_success\n", encoding="utf-8")

        ctx = TestAssistant(root).inspect()
        assert ctx.uncovered == []
        assert ctx.next_scenario is None
        assert "All scenarios are covered" in ctx.actionable_instruction


def test_assist_reports_missing_spec_file_for_active_feature():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("Vanishing Feature", "Audit test")
        spec_md = workflow.feature_dir("vanishing-feature") / "spec.md"
        spec_md.unlink()

        ctx = TestAssistant(root).inspect()
        assert ctx.feature == "vanishing-feature"
        assert ctx.total_scenarios == 0
        assert "spec.md missing" in ctx.actionable_instruction


def test_assist_instructs_to_advance_stage_before_tdd():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("Early Stage Feature", "Audit test")
        spec_md = workflow.feature_dir("early-stage-feature") / "spec.md"
        spec_md.write_text(
            "# Spec: Early Stage Feature\n\n@s1\nScenario: One\n  Given a\n  When b\n  Then c\n",
            encoding="utf-8",
        )

        ctx = TestAssistant(root).inspect()
        assert ctx.stage == "spec"
        assert "Advance through plan/tasks" in ctx.actionable_instruction


def test_assist_falls_back_when_no_scenario_matches_reported_uncovered_tag(
    monkeypatch,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("Mismatch Feature", "Audit test")
        spec_md = workflow.feature_dir("mismatch-feature") / "spec.md"
        spec_md.write_text(
            "# Spec: Mismatch Feature\n\n@s1\nScenario: One\n  Given a\n  When b\n  Then c\n",
            encoding="utf-8",
        )
        workflow.create_plan()
        workflow.create_tasks()
        workflow.begin_work()

        # Force a traceability report whose uncovered tag does not correspond to any
        # extracted scenario, so the lookup loop in inspect() exhausts without a match.
        def fake_find_test_mappings(scenarios, root, feature_dir=None, check_results=None):
            return TraceabilityReport(
                feature="mismatch-feature", scenarios=scenarios, uncovered=["@does-not-exist"]
            )

        monkeypatch.setattr(assist_module, "find_test_mappings", fake_find_test_mappings)

        ctx = TestAssistant(root).inspect()
        assert ctx.next_scenario is None
        assert "All scenarios are covered" in ctx.actionable_instruction
