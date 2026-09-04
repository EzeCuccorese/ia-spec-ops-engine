from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spec.core.paths import PathBoundary
from spec.governance.audit import ProjectAuditor
from spec.spec.trace import extract_scenarios, find_test_mappings
from spec.spec.workflow import Stage, Workflow


@dataclass
class JudgeContext:
    feature: str
    stage: str
    spec_content: str
    scenarios: list[str]
    traceability_summary: str
    work_log: str
    audit_passed: bool
    audit_summary: str
    prompt_for_llm: str

    def to_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature,
            "stage": self.stage,
            "scenarios": self.scenarios,
            "traceability_summary": self.traceability_summary,
            "audit_passed": self.audit_passed,
            "audit_summary": self.audit_summary,
            "prompt_for_llm": self.prompt_for_llm,
        }


class SpecJudge:
    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.root = self.boundary.root

    def evaluate_context(self) -> JudgeContext:
        workflow = Workflow(self.root)
        status = workflow.status()
        if status is None or status.stage == Stage.COMPLETE:
            raise RuntimeError("No active specification to judge.")

        feature_dir = workflow.feature_dir(status.feature)
        spec_path = feature_dir / "spec.md"
        work_path = feature_dir / "work.md"

        spec_content = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        work_log = work_path.read_text(encoding="utf-8") if work_path.is_file() else ""

        scenarios = extract_scenarios(spec_content)
        trace = find_test_mappings(scenarios, self.root, feature_dir=feature_dir)
        trace_summary = f"{trace.covered_count}/{trace.total} scenarios mapped"
        if trace.uncovered:
            trace_summary += f" (Missing: {', '.join(trace.uncovered)})"

        auditor = ProjectAuditor(self.root)
        audit_report = auditor.audit()
        audit_summary = f"{'PASS' if audit_report.passed else 'FAIL'} ({sum(1 for i in audit_report.items if i.passed)}/{len(audit_report.items)} checkpoints)"

        prompt = (
            f"# Role: The Judge (Software Craftsmanship Auditor)\n\n"
            f"You are reviewing the active implementation of feature '{status.feature}'.\n"
            f"Your job is to prune unrequested code and verify that tests genuinely cover the contract.\n\n"
            f"## 1. Specification Contract\n{spec_content}\n\n"
            f"## 2. Work Log & TDD Cycles\n{work_log or 'No work.md recorded.'}\n\n"
            f"## 3. Scenario Traceability\n{trace_summary}\n\n"
            f"## 4. Project Checkpoints (C1-C6)\n{audit_summary}\n\n"
            f"## Instructions for the LLM Judge:\n"
            f"1. Check if all @s scenarios are covered by concrete tests.\n"
            f"2. Inspect if code contains unrequested scope (YAGNI) or empty assertions.\n"
            f"3. Emit your verdict: 'VERDICT: APPROVED' or 'VERDICT: CHANGES_REQUESTED' with bullet points."
        )

        return JudgeContext(
            feature=status.feature,
            stage=status.stage.value,
            spec_content=spec_content,
            scenarios=[s.tag for s in scenarios],
            traceability_summary=trace_summary,
            work_log=work_log,
            audit_passed=audit_report.passed,
            audit_summary=audit_summary,
            prompt_for_llm=prompt,
        )

    def record_verdict(self, verdict: str, remarks: str = "") -> Path:
        workflow = Workflow(self.root)
        status = workflow.status()
        if status is None:
            raise RuntimeError("No active specification to record verdict.")

        feature_dir = workflow.feature_dir(status.feature)
        judge_path = feature_dir / "judge.md"
        norm_verdict = "APPROVED" if "APPROVED" in verdict.upper() else "CHANGES_REQUESTED"

        content = (
            f"# Judge Review: {status.feature}\n\n"
            f"**Verdict**: {norm_verdict}\n\n"
            f"## Remarks\n{remarks or 'No additional remarks.'}\n"
        )
        judge_path.write_text(content, encoding="utf-8")
        return judge_path
