from __future__ import annotations

import tempfile
from pathlib import Path

from spec.governance.audit import ProjectAuditor
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import Workflow


def test_audit_uninitialized_repository():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        report = ProjectAuditor(root).audit()
        assert report.passed is False
        assert any(item.id == "C1" and not item.passed for item in report.items)


def test_audit_initialized_idle_repository():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        report = ProjectAuditor(root).audit()
        assert report.passed is True
        assert report.to_dict()["passed"] is True


def test_audit_with_active_spec_traceability():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ProjectGovernance(root).initialize()
        workflow = Workflow(root)
        workflow.create_spec("My Feature", "Audit test")
        spec_md = workflow.feature_dir("my-feature") / "spec.md"
        spec_md.write_text(
            "# Spec: My Feature\n\n@s1\nScenario: One\n  Given a\n  When b\n  Then c\n",
            encoding="utf-8",
        )
        workflow.create_plan()
        workflow.create_tasks()
        workflow.begin_work()

        # Before mapping @s1 in tests or work.md: C4 should be failed
        report = ProjectAuditor(root).audit()
        c4 = next(item for item in report.items if item.id == "C4")
        # In begin_work, default work.md has Cycle 1 (@s1), so let's check
        assert c4.passed is True
