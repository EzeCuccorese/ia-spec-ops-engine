import json
import sys
from pathlib import Path

from spec.cli import run_doctor, run_verify
from spec.core.result import CheckStatus
from spec.spec.workflow import Stage, Workflow


def test_doctor_json_has_stable_contract(capsys) -> None:
    assert run_doctor(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["spec_version"]
    assert payload["python_version"]
    assert payload["platform"]


def test_verify_executes_config_and_records_workflow_evidence(tmp_path: Path, capsys) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    config = tmp_path / ".spec/verification.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "smoke",
                        "command": [sys.executable, "-c", "print('verified')"],
                    }
                ],
            }
        )
    )

    assert run_verify(tmp_path, as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    snapshot = workflow.status()
    assert payload["status"] == "PASS"
    assert snapshot is not None
    assert snapshot.stage is Stage.VERIFY
    assert snapshot.verification_status is CheckStatus.PASS


def test_cli_new_command_creates_specification(tmp_path: Path) -> None:
    import pytest

    from spec.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["new", "Direct Feature", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert (tmp_path / ".spec/specs/direct-feature/spec.md").exists()


def test_cli_audit_command(tmp_path: Path, capsys) -> None:
    import pytest
    from spec.cli import main
    from spec.governance.project import ProjectGovernance

    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["audit", "--root", str(tmp_path), "--json"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True


def test_verify_includes_scenario_traceability(tmp_path: Path, capsys) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Trace Feature", "Description")
    spec_md = workflow.feature_dir("trace-feature") / "spec.md"
    spec_md.write_text(
        "# Spec: Trace Feature\n\n@s1\nScenario: First\n  Given a\n  When b\n  Then c\n",
        encoding="utf-8",
    )
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    config = tmp_path / ".spec/verification.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "smoke",
                        "command": [sys.executable, "-c", "print('verified')"],
                    }
                ],
            }
        )
    )

    assert run_verify(tmp_path, as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "traceability" in payload
    assert payload["traceability"]["total"] == 1
    assert payload["traceability"]["covered"] == 1


def test_cli_test_assist_command(tmp_path: Path, capsys) -> None:
    import pytest
    from spec.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["test-assist", "--root", str(tmp_path), "--json"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "idle"


def test_cli_judge_command(tmp_path: Path, capsys) -> None:
    import pytest
    from spec.cli import main
    from spec.governance.project import ProjectGovernance

    ProjectGovernance(tmp_path).initialize()
    workflow = Workflow(tmp_path)
    workflow.create_spec("My Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()

    with pytest.raises(SystemExit) as exc:
        main(["judge", "--root", str(tmp_path), "--approve", "--remarks", "All good", "--json"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "RECORDED"
    assert payload["verdict"] == "APPROVED"

