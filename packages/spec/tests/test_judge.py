from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from spec.governance.judge import SpecJudge
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import Workflow


def test_judge_no_active_spec_raises():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        with pytest.raises(RuntimeError, match="No active specification"):
            SpecJudge(root).evaluate_context()


def test_judge_generates_evaluation_context():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("Core Logic", "Feature to judge")
        spec_md = workflow.feature_dir("core-logic") / "spec.md"
        spec_md.write_text(
            "# Spec: Core Logic\n\n@s1\nScenario: Base case\n  Given a\n  When b\n  Then c\n",
            encoding="utf-8",
        )
        workflow.create_plan()
        workflow.create_tasks()
        workflow.begin_work()

        ctx = SpecJudge(root).evaluate_context()
        assert ctx.feature == "core-logic"
        assert "@s1" in ctx.scenarios
        assert "The Judge" in ctx.prompt_for_llm
        assert ctx.audit_passed is True


def test_judge_records_verdict():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("Core Logic", "Feature to judge")
        workflow.create_plan()
        workflow.create_tasks()
        workflow.begin_work()

        judge_path = SpecJudge(root).record_verdict("APPROVED", "All clean and tested.")
        assert judge_path.is_file()
        content = judge_path.read_text(encoding="utf-8")
        assert "**Verdict**: APPROVED" in content
        assert "All clean and tested." in content
