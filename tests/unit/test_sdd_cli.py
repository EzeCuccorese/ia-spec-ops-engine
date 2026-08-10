import json
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
