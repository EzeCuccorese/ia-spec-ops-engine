from __future__ import annotations

import tempfile
from pathlib import Path

from spec.governance.project import ProjectGovernance
from spec.spec.assist import TestAssistant
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

        # In begin_work, work.md has Cycle 1 (@s1), so @s2 should be next!
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

        work_md = workflow.feature_dir("login-feature") / "work.md"
        work_md.write_text("# Work Log\n\n- @s1 -> test_login_success\n", encoding="utf-8")

        ctx = TestAssistant(root).inspect()
        assert ctx.uncovered == []
        assert ctx.next_scenario is None
        assert "All scenarios are covered" in ctx.actionable_instruction
