import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch
from sdd_engine.lifecycle import feature

def test_set_active_feature(tmp_path):
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        feature.set_feature("test-auth-feature")
        
        feature_file = tmp_path / ".specify" / "feature.json"
        assert feature_file.exists()
        
        with open(feature_file) as f:
            content = json.load(f)
            assert content["active_feature"] == "test-auth-feature"
            assert content["current_phase"] == "specify"

def test_update_phase(tmp_path):
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        feature.set_feature("my-feature")
        feature.update_phase("plan")
        
        feature_file = tmp_path / ".specify" / "feature.json"
        with open(feature_file) as f:
            content = json.load(f)
            assert content["current_phase"] == "plan"

def test_get_status_with_artifacts(tmp_path, capsys):
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        feature.set_feature("user-api")
        
        spec_dir = tmp_path / ".specify" / "specs" / "user-api"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text("# Spec")
        (spec_dir / "plan.md").write_text("# Plan")
        
        feature.status()
        captured = capsys.readouterr()
        assert "user-api" in captured.out


def test_sdd_verify_table(capsys):
    import sdd_engine.cli as sdd
    from sdd_engine.core.invariants import VerificationPayload

    mock_payload = VerificationPayload(
        passed=True,
        linter_status="PASS",
        test_status="PASS",
        confirmation_read_status="PASS",
        security_status="PASS",
        remediation_instructions="",
        details={"target_dir": "/tmp/test", "stack": "python"},
    )
    with patch("sdd_engine.verify.run_verification", return_value=mock_payload):
        with patch.object(sys, "argv", ["sdd", "verify", "--dir", "/tmp/test"]):
            sdd.main()
            captured = capsys.readouterr()
            assert "SDD Automated Verification Result" in captured.out
            assert "PASS" in captured.out
            assert "python" in captured.out


def test_sdd_verify_json(capsys):
    import sdd_engine.cli as sdd
    from sdd_engine.core.invariants import VerificationPayload

    mock_payload = VerificationPayload(
        passed=True,
        linter_status="PASS",
        test_status="PASS",
        confirmation_read_status="PASS",
        security_status="PASS",
        remediation_instructions="",
        details={"target_dir": "/tmp/test", "stack": "python"},
    )
    with patch("sdd_engine.verify.run_verification", return_value=mock_payload):
        with patch.object(sys, "argv", ["sdd", "verify", "--dir", "/tmp/test", "--json"]):
            sdd.main()
            captured = capsys.readouterr()
            data = json.loads(captured.out.strip())
            assert data["passed"] is True
            assert data["linter_status"] == "PASS"


def test_sdd_hook_pre_tool_approved(capsys):
    import sdd_engine.cli as sdd

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
    import sdd_engine.cli as sdd

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
    import sdd_engine.cli as sdd
    from sdd_engine.core.invariants import VerificationPayload

    mock_payload = VerificationPayload(
        passed=True,
        linter_status="PASS",
        test_status="PASS",
        confirmation_read_status="PASS",
        security_status="PASS",
    )
    with patch("sdd_engine.hooks.run_verification", return_value=mock_payload):
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
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        with pytest.raises((SystemExit, Exception)):
            feature.set_feature("")


def test_sdd_specify_with_name_sets_active_feature(tmp_path):
    import sdd_engine.cli as sdd
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        with patch.object(sys, "argv", ["sdd", "specify", "auto-feature"]):
            sdd.main()
            assert feature.get_active_feature(repo_root=tmp_path) == "auto-feature"


def test_set_feature_creates_worktree_on_protected_branch(tmp_path, monkeypatch):
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        def mock_run_command_safe(cmd, cwd=None):
            if "branch --show-current" in " ".join(cmd):
                return (0, "main", "")
            return (0, "", "")

        called_worktree = []
        def mock_create_worktree(branch, from_branch=None, start_dir=None):
            called_worktree.append((branch, from_branch))
            return 0

        monkeypatch.setattr("sdd_engine.feature.get_repo_root", lambda: tmp_path)
        monkeypatch.setattr("workspace_engine.cli.create_worktree.create_worktree", mock_create_worktree)
        monkeypatch.setattr("sdd_engine.utils.run_command_safe", mock_run_command_safe)

        feature.set_feature("feat-isolated", from_branch="develop")
        assert called_worktree == [("feature/feat-isolated", "develop")]


def test_list_features(tmp_path, capsys):
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        spec_dir = tmp_path / ".specify" / "specs" / "feat-sales"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text("# Spec Sales")
        (spec_dir / "plan.md").write_text("# Plan Sales")

        feature.set_feature("feat-sales", no_worktree=True)
        feats = feature.list_features(repo_root=tmp_path)
        
        assert len(feats) == 1
        assert feats[0]["name"] == "feat-sales"
        assert feats[0]["phase"] == "plan"
        assert feats[0]["is_active"] is True
        
        captured = capsys.readouterr()
        assert "Catálogo de Características SDD" in captured.out
        assert "feat-sales" in captured.out


def test_sdd_feature_direct_name_routing(tmp_path):
    import sdd_engine.cli as sdd
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        with patch.object(sys, "argv", ["sdd", "feature", "direct-feat", "--from-branch", "main"]):
            with patch("workspace_engine.cli.create_worktree.create_worktree") as mock_wt:
                sdd.main()
                assert feature.get_active_feature(repo_root=tmp_path) == "direct-feat"


def test_sdd_feature_set_routing(tmp_path):
    import sdd_engine.cli as sdd
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        with patch.object(sys, "argv", ["sdd", "feature", "set", "explicit-feat"]):
            with patch("workspace_engine.cli.create_worktree.create_worktree"):
                sdd.main()
                assert feature.get_active_feature(repo_root=tmp_path) == "explicit-feat"


def test_sdd_feature_get_and_status(tmp_path, capsys):
    import sdd_engine.cli as sdd
    with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
        feature.set_feature("status-feat", no_worktree=True)
        with patch.object(sys, "argv", ["sdd", "feature", "get"]):
            sdd.main()
        captured = capsys.readouterr()
        assert "status-feat" in captured.out

        with patch.object(sys, "argv", ["sdd", "feature", "status"]):
            sdd.main()
        captured = capsys.readouterr()
        assert "Active Feature: status-feat" in captured.out


def test_analyzer_raises_exceptions(tmp_path):
    import sdd_engine.harness.analyzer as analyzer
    from sdd_engine.core.exceptions import AnalysisError, FeatureNotFoundError


    with patch("sdd_engine.harness.analyzer.get_repo_root", return_value=tmp_path):

        # No feature set -> FeatureNotFoundError
        with pytest.raises(FeatureNotFoundError):
            analyzer.analyze()

        # Incomplete feature artifacts -> AnalysisError
        feature.set_feature("incomplete-feat", no_worktree=True)
        with patch("sdd_engine.feature.get_repo_root", return_value=tmp_path):
            with pytest.raises(AnalysisError):
                analyzer.analyze("incomplete-feat")


def test_sdd_main_module_import():
    import runpy
    with patch.object(sys, "argv", ["sdd", "--help"]):
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("sdd_engine.cli", run_name="__main__")
        assert exc.value.code == 0






