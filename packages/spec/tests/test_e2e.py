import json
import sys
from pathlib import Path

import pytest

from spec.cli import main


def invoke(*args: str) -> int:
    with pytest.raises(SystemExit) as exited:
        main(list(args))
    return int(exited.value.code)


def test_personal_governance_sdd_flow_end_to_end(tmp_path: Path, capsys) -> None:
    root = str(tmp_path)

    assert invoke("init", "--root", root) == 0
    assert invoke("agent", "install", "--root", root) == 0
    assert invoke(
        "spec",
        "new",
        "Safe change",
        "--description",
        "Prove the governed workflow.",
        "--root",
        root,
    ) == 0
    assert invoke("plan", "--root", root) == 0
    assert invoke("tasks", "--root", root) == 0
    assert invoke("work", "--root", root) == 0

    (tmp_path / ".spec/verification.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "smoke",
                        "command": [sys.executable, "-c", "print('e2e-pass')"],
                    }
                ],
            }
        )
        + "\n"
    )
    assert invoke("verify", "--root", root, "--json") == 0
    assert invoke("finish", "--root", root) == 0
    assert invoke("status", "--root", root, "--json") == 0

    output = capsys.readouterr().out
    assert '"status": "PASS"' in output
    assert '"stage": "complete"' in output
    assert (tmp_path / "AGENTS.md").is_file()
    evidence = list((tmp_path / ".spec/evidence/safe-change").glob("*.json"))
    assert len(evidence) == 1

    assert invoke("agent", "uninstall", "--root", root) == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert invoke("agent", "uninstall", "--root", root, "--apply") == 0
    assert not (tmp_path / "AGENTS.md").exists()
