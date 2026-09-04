from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from spec.core.paths import PathBoundary
from spec.core.result import CheckStatus, VerificationReport


class WorkflowError(RuntimeError):
    """Base error for specification lifecycle operations."""


class InvalidTransitionError(WorkflowError):
    """The requested transition lacks required state or artifacts."""


class ArtifactExistsError(WorkflowError):
    """Creating an artifact would overwrite existing user content."""


class CorruptStateError(WorkflowError):
    """Persisted workflow state is invalid or unsupported."""


class Stage(StrEnum):
    SPEC = "spec"
    PLAN = "plan"
    TASKS = "tasks"
    WORK = "work"
    VERIFY = "verify"
    COMPLETE = "complete"


@dataclass(frozen=True)
class WorkflowSnapshot:
    feature: str
    stage: Stage
    updated_at: str
    verification_status: CheckStatus | None = None
    evidence_path: str | None = None


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    if not slug:
        raise ValueError("Feature name must contain at least one letter or number")
    return slug


class Workflow:
    schema_version = 1

    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)
        self.state_path = self.boundary.resolve(".spec/state.json")

    def status(self) -> WorkflowSnapshot | None:
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != self.schema_version:
                raise CorruptStateError("Unsupported workflow state schema")
            return WorkflowSnapshot(
                feature=str(data["active_feature"]),
                stage=Stage(data["stage"]),
                updated_at=str(data["updated_at"]),
                verification_status=(
                    CheckStatus(data["verification_status"])
                    if data.get("verification_status") is not None
                    else None
                ),
                evidence_path=(
                    str(data["evidence_path"]) if data.get("evidence_path") is not None else None
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptStateError(f"Invalid workflow state: {self.state_path}") from exc

    def feature_dir(self, feature: str) -> Path:
        return self.boundary.resolve(f".spec/specs/{slugify(feature)}")

    def create_spec(self, name: str, description: str = "") -> WorkflowSnapshot:
        feature = slugify(name)
        directory = self.feature_dir(feature)
        spec_path = directory / "spec.md"
        current = self.status()
        if current is not None and current.stage is not Stage.COMPLETE:
            if current.feature != feature:
                raise InvalidTransitionError(
                    f"Feature {current.feature} is already active at stage {current.stage}"
                )
            raise ArtifactExistsError(
                f"Spec already exists and will not be overwritten: {spec_path}"
            )
        if spec_path.exists():
            if current is None:
                self._require_nonempty(spec_path, "spec.md")
                return self._persist(feature, Stage.SPEC)
            raise ArtifactExistsError(
                f"Spec already exists and will not be overwritten: {spec_path}"
            )
        content = (
            f"# Spec: {name.strip()}\n\n"
            "## Purpose\n\n"
            f"{description.strip() or 'Describe the intended outcome.'}\n\n"
            "## Requirements\n\n"
            "- REQ-001: Define the observable behavior.\n\n"
            "## Acceptance criteria\n\n"
            "- [ ] AC-001: Add a verifiable acceptance criterion.\n\n"
            "## Out of scope\n\n"
            "- Document behavior intentionally excluded from this change.\n"
        )
        self._create_artifact(spec_path, content)
        return self._persist(feature, Stage.SPEC)

    def create_plan(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None:
            raise InvalidTransitionError("Cannot create a plan without an active spec")
        if current.stage is not Stage.SPEC:
            raise InvalidTransitionError(
                f"Plan requires stage spec, current stage is {current.stage}"
            )
        directory = self.feature_dir(current.feature)
        self._require_nonempty(directory / "spec.md", "spec.md")
        plan_path = directory / "plan.md"
        if plan_path.exists():
            self._require_nonempty(plan_path, "plan.md")
            return self._persist(current.feature, Stage.PLAN)
        content = (
            f"# Plan: {current.feature}\n\n"
            "## Approach\n\nDescribe the smallest viable implementation.\n\n"
            "## Contracts\n\nList changed interfaces, schemas, commands, and files.\n\n"
            "## Verification\n\nMap each requirement to executable evidence.\n\n"
            "## Risks and rollback\n\nDocument failure modes and recovery.\n"
        )
        self._create_artifact(plan_path, content)
        return self._persist(current.feature, Stage.PLAN)

    def create_tasks(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None or current.stage is not Stage.PLAN:
            actual = current.stage if current else "none"
            raise InvalidTransitionError(f"Tasks require an active plan; current stage is {actual}")
        directory = self.feature_dir(current.feature)
        self._require_nonempty(directory / "plan.md", "plan.md")
        tasks_path = directory / "tasks.md"
        if tasks_path.exists():
            self._require_nonempty(tasks_path, "tasks.md")
            return self._persist(current.feature, Stage.TASKS)
        content = (
            f"# Tasks: {current.feature}\n\n"
            "- [ ] T-001: Add a failing test or executable reproduction.\n"
            "- [ ] T-002: Implement the smallest change that satisfies the contract.\n"
            "- [ ] T-003: Run required verification and record evidence.\n"
        )
        self._create_artifact(tasks_path, content)
        return self._persist(current.feature, Stage.TASKS)

    def begin_work(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None or current.stage is not Stage.TASKS:
            actual = current.stage if current else "none"
            raise InvalidTransitionError(f"Work requires active tasks; current stage is {actual}")
        directory = self.feature_dir(current.feature)
        self._require_nonempty(directory / "tasks.md", "tasks.md")
        work_path = directory / "work.md"
        if not work_path.exists():
            content = (
                f"# Work Log: {current.feature}\n\n"
                "## TDD Cycles (Red -> Green -> Refactor)\n"
                "- [ ] Cycle 1 (@s1): Failing test -> Minimal code -> Refactor\n\n"
                "## Traceability (@s -> test)\n"
                "<!-- Map each scenario tag to its implementing test. -->\n"
            )
            self._create_artifact(work_path, content)
        return self._persist(current.feature, Stage.WORK)

    def record_verification(self, report: VerificationReport) -> tuple[WorkflowSnapshot, Path]:
        current = self.status()
        allowed = {Stage.WORK, Stage.VERIFY}
        if current is None or current.stage not in allowed:
            actual = current.stage if current else "none"
            raise InvalidTransitionError(
                f"Verification requires active work; current stage is {actual}"
            )
        recorded_at = datetime.now(UTC)
        relative_path = Path(
            ".spec",
            "evidence",
            current.feature,
            f"{recorded_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}.json",
        )
        evidence_path = self.boundary.resolve(relative_path)
        payload = {
            "schema_version": 1,
            "feature": current.feature,
            "recorded_at": recorded_at.isoformat(),
            "report": report.to_dict(),
        }
        self._create_artifact(evidence_path, json.dumps(payload, indent=2) + "\n")
        snapshot = self._persist(
            current.feature,
            Stage.VERIFY,
            verification_status=report.status,
            evidence_path=str(relative_path),
        )
        return snapshot, evidence_path

    def finish(self) -> WorkflowSnapshot:
        current = self.status()
        if current is None or current.stage is not Stage.VERIFY:
            actual = current.stage if current else "none"
            raise InvalidTransitionError(
                f"Finish requires a verification attempt; current stage is {actual}"
            )
        if current.verification_status is not CheckStatus.PASS:
            raise InvalidTransitionError("Finish requires verification status PASS")
        if current.evidence_path is None:
            raise InvalidTransitionError("Finish requires recorded verification evidence")
        self._require_nonempty(
            self.boundary.resolve(current.evidence_path), "verification evidence"
        )
        feature_dir = self.feature_dir(current.feature)
        spec_file = feature_dir / "spec.md"
        if spec_file.is_file():
            from spec.spec.trace import extract_scenarios, find_test_mappings

            scenarios = extract_scenarios(spec_file.read_text(encoding="utf-8"))
            if scenarios:
                report = find_test_mappings(scenarios, self.boundary.root, feature_dir=feature_dir)
                if not report.is_complete:
                    missing = ", ".join(report.uncovered)
                    raise InvalidTransitionError(
                        f"Finish rejected: Scenarios lacking test mapping: {missing}"
                    )
        return self._persist(
            current.feature,
            Stage.COMPLETE,
            verification_status=current.verification_status,
            evidence_path=current.evidence_path,
        )

    @staticmethod
    def _require_nonempty(path: Path, label: str) -> None:
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise InvalidTransitionError(f"Required artifact is missing or empty: {label}")

    @staticmethod
    def _create_artifact(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ArtifactExistsError(
                f"Artifact exists and will not be overwritten: {path}"
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def _persist(
        self,
        feature: str,
        stage: Stage,
        *,
        verification_status: CheckStatus | None = None,
        evidence_path: str | None = None,
    ) -> WorkflowSnapshot:
        snapshot = WorkflowSnapshot(
            feature=feature,
            stage=stage,
            updated_at=datetime.now(UTC).isoformat(),
            verification_status=verification_status,
            evidence_path=evidence_path,
        )
        payload = {
            "schema_version": self.schema_version,
            "active_feature": snapshot.feature,
            "stage": snapshot.stage.value,
            "updated_at": snapshot.updated_at,
            "verification_status": (
                snapshot.verification_status.value if snapshot.verification_status else None
            ),
            "evidence_path": snapshot.evidence_path,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".state-", dir=self.state_path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            temporary.replace(self.state_path)
        finally:
            temporary.unlink(missing_ok=True)
        return snapshot
