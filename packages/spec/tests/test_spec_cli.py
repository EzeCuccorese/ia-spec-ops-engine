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
