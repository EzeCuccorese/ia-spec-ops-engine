import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch
from devscripts.sdd import feature

def test_set_active_feature(tmp_path):
    with patch("devscripts.sdd.feature.get_repo_root", return_value=tmp_path):
        feature.set_feature("test-auth-feature")
        
        feature_file = tmp_path / ".specify" / "feature.json"
        assert feature_file.exists()
        
        with open(feature_file) as f:
            content = json.load(f)
            assert content["active_feature"] == "test-auth-feature"
            assert content["current_phase"] == "specify"

def test_update_phase(tmp_path):
    with patch("devscripts.sdd.feature.get_repo_root", return_value=tmp_path):
        feature.set_feature("my-feature")
        feature.update_phase("plan")
        
        feature_file = tmp_path / ".specify" / "feature.json"
        with open(feature_file) as f:
            content = json.load(f)
            assert content["current_phase"] == "plan"

def test_get_status_with_artifacts(tmp_path, capsys):
    with patch("devscripts.sdd.feature.get_repo_root", return_value=tmp_path):
        feature.set_feature("user-api")
        
        spec_dir = tmp_path / ".specify" / "specs" / "user-api"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text("# Spec")
        (spec_dir / "plan.md").write_text("# Plan")
        
        feature.status()
        captured = capsys.readouterr()
        assert "user-api" in captured.out


def test_sdd_verify_table(capsys):
    from devscripts.cli.sdd import sdd
    from devscripts.sdd.invariants import VerificationPayload

    mock_payload = VerificationPayload(
        passed=True,
        linter_status="PASS",
        test_status="PASS",
        confirmation_read_status="PASS",
        security_status="PASS",
        remediation_instructions="",
        details={"target_dir": "/tmp/test", "stack": "python"},
    )
    with patch("devscripts.sdd.verify.run_verification", return_value=mock_payload):
        with patch.object(sys, "argv", ["sdd", "verify", "--dir", "/tmp/test"]):
            sdd.main()
            captured = capsys.readouterr()
            assert "Resultado de Verificación Automatizada SDD" in captured.out
            assert "PASS" in captured.out
            assert "python" in captured.out


def test_sdd_verify_json(capsys):
    from devscripts.cli.sdd import sdd
    from devscripts.sdd.invariants import VerificationPayload

    mock_payload = VerificationPayload(
        passed=True,
        linter_status="PASS",
        test_status="PASS",
        confirmation_read_status="PASS",
        security_status="PASS",
        remediation_instructions="",
        details={"target_dir": "/tmp/test", "stack": "python"},
    )
    with patch("devscripts.sdd.verify.run_verification", return_value=mock_payload):
        with patch.object(sys, "argv", ["sdd", "verify", "--dir", "/tmp/test", "--json"]):
            sdd.main()
            captured = capsys.readouterr()
            data = json.loads(captured.out.strip())
            assert data["passed"] is True
            assert data["linter_status"] == "PASS"


def test_sdd_hook_pre_tool_approved(capsys):
    from devscripts.cli.sdd import sdd

    with patch.object(sys, "argv", ["sdd", "hook", "pre-tool", "--tool-name", "write_to_file", "--tool-args", '{"TargetFile": "foo.py"}']):
        sdd.main()
        captured = capsys.readouterr()
        output = captured.out
        json_start = output.find("{")
        assert json_start != -1
        data = json.loads(output[json_start:])
        assert data["approved"] is True
        assert data["reason"] == "Approved"


def test_sdd_hook_pre_tool_blocked(capsys):
    from devscripts.cli.sdd import sdd

    with patch.object(sys, "argv", ["sdd", "hook", "pre-tool", "--tool-name", "run_command", "--tool-args", "rm -rf /"]):
        sdd.main()
        captured = capsys.readouterr()
        output = captured.out
        json_start = output.find("{")
        assert json_start != -1
        data = json.loads(output[json_start:])
        assert data["approved"] is False
        assert "Blocked" in data["reason"]


def test_sdd_hook_post_tool(capsys):
    from devscripts.cli.sdd import sdd
    from devscripts.sdd.invariants import VerificationPayload

    mock_payload = VerificationPayload(
        passed=True,
        linter_status="PASS",
        test_status="PASS",
        confirmation_read_status="PASS",
        security_status="PASS",
    )
    with patch("devscripts.sdd.hooks.run_verification", return_value=mock_payload):
        with patch.object(sys, "argv", ["sdd", "hook", "post-tool", "--tool-name", "write_to_file", "--tool-args", '{"TargetFile": "app.py"}']):
            sdd.main()
            captured = capsys.readouterr()
            output = captured.out
            json_start = output.find("{")
            assert json_start != -1
            data = json.loads(output[json_start:])
            assert data["passed"] is True
            assert data["linter_status"] == "PASS"


def test_set_feature_empty_raises_error(tmp_path):
    with patch("devscripts.sdd.feature.get_repo_root", return_value=tmp_path):
        with pytest.raises(SystemExit):
            feature.set_feature("")


def test_sdd_specify_with_name_sets_active_feature(tmp_path):
    from devscripts.cli.sdd import sdd
    with patch("devscripts.sdd.feature.get_repo_root", return_value=tmp_path):
        with patch.object(sys, "argv", ["sdd", "specify", "auto-feature"]):
            sdd.main()
            assert feature.get_active_feature(repo_root=tmp_path) == "auto-feature"


def test_sdd_adapter_alias(tmp_path):
    from devscripts.cli.sdd import sdd
    with patch("devscripts.adapters.bridge.generate_adapters") as mock_gen:
        with patch.object(sys, "argv", ["sdd", "adapter", "--all", "--target-dir", str(tmp_path)]):
            sdd.main()
            mock_gen.assert_called_once()



