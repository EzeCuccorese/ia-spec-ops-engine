from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spec.core.paths import PathBoundary
from spec.spec.trace import Scenario, extract_scenarios, find_test_mappings
from spec.spec.workflow import Stage, Workflow


@dataclass
class AssistContext:
    feature: str
    stage: str
    total_scenarios: int
    covered_count: int
    uncovered: list[str]
    next_scenario: Scenario | None = None
    work_log_exists: bool = False
    actionable_instruction: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "feature": self.feature,
            "stage": self.stage,
            "total_scenarios": self.total_scenarios,
            "covered_count": self.covered_count,
            "uncovered": self.uncovered,
            "next_scenario": (
                {"tag": self.next_scenario.tag, "title": self.next_scenario.title}
                if self.next_scenario
                else None
            ),
            "work_log_exists": self.work_log_exists,
            "actionable_instruction": self.actionable_instruction,
        }


class TestAssistant:
    __test__ = False

    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.root = self.boundary.root

    def inspect(self) -> AssistContext:
        workflow = Workflow(self.root)
        status = workflow.status()
        if status is None or status.stage == Stage.COMPLETE:
            return AssistContext(
                feature="none",
                stage="idle",
                total_scenarios=0,
                covered_count=0,
                uncovered=[],
                actionable_instruction="No active specification. Run 'spec new <name>' to begin.",
            )

        feature_dir = workflow.feature_dir(status.feature)
        spec_file = feature_dir / "spec.md"
        work_file = feature_dir / "work.md"
        work_log_exists = work_file.is_file()

        if not spec_file.is_file():
            return AssistContext(
                feature=status.feature,
                stage=status.stage.value,
                total_scenarios=0,
                covered_count=0,
                uncovered=[],
                work_log_exists=work_log_exists,
                actionable_instruction=f"spec.md missing for active feature '{status.feature}'.",
            )

        scenarios = extract_scenarios(spec_file.read_text(encoding="utf-8"))
        trace = find_test_mappings(scenarios, self.root, feature_dir=feature_dir)

        next_scenario = None
        if trace.uncovered:
            uncovered_tags = set(trace.uncovered)
            for s in scenarios:
                if s.tag in uncovered_tags:
                    next_scenario = s
                    break

        if status.stage in (Stage.SPEC, Stage.PLAN, Stage.TASKS):
            instruction = f"Current stage is '{status.stage.value}'. Advance through plan/tasks before starting TDD."
        elif next_scenario:
            instruction = (
                f"Next TDD Step: Write failing test for scenario {next_scenario.tag} ({next_scenario.title}), "
                f"then implement minimal code, verify green, and record in work.md."
            )
        else:
            instruction = "All scenarios are covered by tests! Run 'spec verify' before finish."

        return AssistContext(
            feature=status.feature,
            stage=status.stage.value,
            total_scenarios=trace.total,
            covered_count=trace.covered_count,
            uncovered=trace.uncovered,
            next_scenario=next_scenario,
            work_log_exists=work_log_exists,
            actionable_instruction=instruction,
        )
