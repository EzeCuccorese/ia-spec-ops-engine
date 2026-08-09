import json
import pytest
from pathlib import Path
from unittest.mock import patch
from devscripts.cli import sdd

def test_set_active_feature(tmp_path):
    with patch("devscripts.cli.sdd.get_repo_root", return_value=tmp_path):
        data = sdd.set_active_feature("test-auth-feature")
        
        assert data["active_feature"] == "test-auth-feature"
        assert data["current_phase"] == "specify"
        
        feature_file = tmp_path / ".specify" / "feature.json"
        assert feature_file.exists()
        
        with open(feature_file) as f:
            content = json.load(f)
            assert content["active_feature"] == "test-auth-feature"
            assert content["current_phase"] == "specify"

def test_update_phase(tmp_path):
    with patch("devscripts.cli.sdd.get_repo_root", return_value=tmp_path):
        sdd.set_active_feature("my-feature")
        updated = sdd.update_phase("plan")
        
        assert updated is not None
        assert updated["current_phase"] == "plan"
        
        feature_file = tmp_path / ".specify" / "feature.json"
        with open(feature_file) as f:
            content = json.load(f)
            assert content["current_phase"] == "plan"

def test_get_status_with_artifacts(tmp_path):
    with patch("devscripts.cli.sdd.get_repo_root", return_value=tmp_path):
        sdd.set_active_feature("user-api")
        
        spec_dir = tmp_path / ".specify" / "specs" / "user-api"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text("# Spec")
        (spec_dir / "plan.md").write_text("# Plan")
        
        status = sdd.get_status()
        assert status is not None
        assert status["active_feature"] == "user-api"
