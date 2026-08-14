"""
Unit tests for sdd_engine.finish — SDD Feature Finish & PR Cleanup Engine.
"""

import tempfile
from pathlib import Path
import pytest

from sdd_engine.finish import finish_feature, get_current_branch


def test_finish_feature_no_active_feature():
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = finish_feature(target_dir=tmp_dir, create_pr=False)
        assert res is False


def test_finish_feature_resets_state_and_returns(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        spec_dir = td / ".specify"
        spec_dir.mkdir()
        (spec_dir / "feature.json").write_text('{"active_feature": "demo-feat", "current_phase": "converge"}')

        # Mock run_command_safe to simulate git/gh commands
        def mock_run_command_safe(cmd, cwd=None):
            cmd_str = " ".join(cmd)
            if "branch --show-current" in cmd_str:
                return (0, "feature/demo-feat", "")
            if "status --porcelain" in cmd_str:
                return (0, "", "")
            if "push" in cmd_str:
                return (0, "Pushed", "")
            if "gh pr create" in cmd_str:
                return (0, "https://github.com/org/repo/pull/1", "")
            if "worktree list" in cmd_str:
                return (0, f"worktree {td}\nhead 12345", "")
            return (0, "OK", "")

        monkeypatch.setattr("sdd_engine.finish.run_command_safe", mock_run_command_safe)

        res = finish_feature(target_dir=tmp_dir, create_pr=True)
        assert res is True
        assert not (spec_dir / "feature.json").exists()
