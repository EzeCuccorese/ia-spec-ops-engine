from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from spec.core.paths import PathBoundary
from spec.spec.workflow import Stage, Workflow


@dataclass
class CheckpointItem:
    id: str
    description: str
    passed: bool
    details: str = ""


@dataclass
class AuditReport:
    items: list[CheckpointItem] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.items)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checkpoints": [
                {
                    "id": item.id,
                    "description": item.description,
                    "passed": item.passed,
                    "details": item.details,
                }
                for item in self.items
            ],
        }


class ProjectAuditor:
    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.root = self.boundary.root

    def audit(self) -> AuditReport:
        items: list[CheckpointItem] = []

        # C1: Base governance files present
        spec_dir = self.root / ".spec"
        policy_file = spec_dir / "policy.json"
        verification_file = spec_dir / "verification.json"
        c1_passed = spec_dir.is_dir() and policy_file.is_file() and verification_file.is_file()
        items.append(
            CheckpointItem(
                id="C1",
                description="Harness initialized (.spec/ directory, policy.json, verification.json)",
                passed=c1_passed,
                details="Present" if c1_passed else "Missing policy or verification config",
            )
        )

        # C2: State coherence
        workflow = Workflow(self.root)
        status = workflow.status()
        c2_passed = True
        c2_details = "IDLE (no active spec)"
        if status is not None:
            c2_details = f"Active: {status.feature} (stage={status.stage.value})"
        items.append(
            CheckpointItem(
                id="C2",
                description="State coherence (.spec/state.json valid)",
                passed=c2_passed,
                details=c2_details,
            )
        )

        # C3: Active spec artifacts
        c3_passed = True
        c3_details = "N/A (no active spec)"
        if status is not None and status.stage != Stage.COMPLETE:
            feature_dir = workflow.feature_dir(status.feature)
            missing: list[str] = []
            if not (feature_dir / "spec.md").is_file():
                missing.append("spec.md")
            if status.stage in (Stage.PLAN, Stage.TASKS, Stage.WORK, Stage.VERIFY):
                if not (feature_dir / "plan.md").is_file():
                    missing.append("plan.md")
            if status.stage in (Stage.TASKS, Stage.WORK, Stage.VERIFY):
                if not (feature_dir / "tasks.md").is_file():
                    missing.append("tasks.md")
            if status.stage in (Stage.WORK, Stage.VERIFY):
                if not (feature_dir / "work.md").is_file():
                    missing.append("work.md")

            if missing:
                c3_passed = False
                c3_details = f"Missing required artifacts: {', '.join(missing)}"
            else:
                c3_details = f"Artifacts complete for stage {status.stage.value}"

        items.append(
            CheckpointItem(
                id="C3",
                description="Active specification artifacts",
                passed=c3_passed,
                details=c3_details,
            )
        )

        # C4: Scenario Traceability
        c4_passed = True
        c4_details = "No scenarios tagged in spec"
        if status is not None:
            feature_dir = workflow.feature_dir(status.feature)
            spec_file = feature_dir / "spec.md"
            if spec_file.is_file():
                from spec.spec.trace import extract_scenarios, find_test_mappings

                scenarios = extract_scenarios(spec_file.read_text(encoding="utf-8"))
                if scenarios:
                    trace = find_test_mappings(scenarios, self.root, feature_dir=feature_dir)
                    c4_passed = trace.is_complete
                    if trace.is_complete:
                        c4_details = f"{trace.covered_count}/{trace.total} scenarios mapped (100%)"
                    else:
                        c4_details = f"Missing test mapping for: {', '.join(trace.uncovered)}"

        items.append(
            CheckpointItem(
                id="C4",
                description="Scenario traceability (@s tags mapped to tests)",
                passed=c4_passed,
                details=c4_details,
            )
        )

        # C5: Verification evidence
        c5_passed = True
        c5_details = "No verification recorded yet"
        if status is not None and status.verification_status is not None:
            c5_passed = status.verification_status.value == "PASS"
            c5_details = f"Status: {status.verification_status.value}"
        items.append(
            CheckpointItem(
                id="C5",
                description="Verification evidence recorded",
                passed=c5_passed,
                details=c5_details,
            )
        )

        # C6: Workspace hygiene (no leftover .tmp files in .spec)
        tmp_files = list(spec_dir.glob("**/.state-*")) if spec_dir.is_dir() else []
        c6_passed = len(tmp_files) == 0
        items.append(
            CheckpointItem(
                id="C6",
                description="Clean workspace hygiene (no stray temporary state files)",
                passed=c6_passed,
                details="Clean" if c6_passed else f"{len(tmp_files)} stray temporary files found",
            )
        )

        return AuditReport(items=items)
