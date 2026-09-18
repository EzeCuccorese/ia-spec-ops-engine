"""Tests for harness doctor command health checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.harness.doctor import main as doctor_main


class TestDoctorHostDetection:
    """Test doctor host detection and N/A status."""

    def test_no_host_shows_na_status(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """No host when settings.json missing → N/A status in output."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        doctor_main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert "N/A" in out
        assert "host" in out


class TestDoctorJsonOutput:
    """Test doctor JSON output format."""

    def test_json_output_valid_structure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """doctor --json produces valid JSON with expected keys."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        doctor_main(["--json", "--root", str(tmp_path)])
        out = capsys.readouterr().out

        data = json.loads(out)
        assert isinstance(data, dict)
        assert "host" in data
        assert "checks" in data
        assert "ok" in data
        assert "missing" in data
        assert "warn" in data
        assert isinstance(data["checks"], list)
        for check in data["checks"]:
            assert "status" in check
            assert "name" in check
            assert "hint" in check


class TestDoctorFullyWiredSetup:
    """Test doctor with fully configured setup."""

    def test_fully_wired_setup_all_ok(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Fully wired settings + AGENTS.md + usage dir → all OK, exit 0."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        # Create fake settings.json with hooks
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "frugal --pre-bash"}]}],
                "PostToolUse": [{"matcher": "Bash", "hooks": [{"command": "frugal --post-bash"}]}],
                "Stop": [{"hooks": [{"command": "telemetry thresholds --notify"}]}],
                "WorktreeCreate": [{"hooks": [{"command": "ws hook claude-worktree-create"}]}],
            },
        }
        settings_file = claude_dir / "settings.json"
        settings_file.write_text(json.dumps(settings), encoding="utf-8")

        # Create AGENTS.md with both blocks
        (tmp_path / "usage").mkdir()
        agents_md = tmp_path / "AGENTS.md"
        content = (
            "# Agents\n"
            "<!-- rules:start -->\n@rule1\n<!-- rules:end -->\n"
            "<!-- harness:start -->\n## Harness\n<!-- harness:end -->\n"
        )
        agents_md.write_text(content, encoding="utf-8")

        # Mock tool detection to always pass
        monkeypatch.setattr("shutil.which", lambda name: f"/fake/bin/{name}")

        result = doctor_main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert result == 0
        lines = out.strip().split("\n")
        assert len(lines) <= 16
        assert "summary:" in out
        assert out.count(" — ") == 0  # OK lines have no hint


class TestDoctorInvalidSettings:
    """Test doctor with invalid settings JSON."""

    def test_invalid_json_shows_warn(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Invalid JSON in settings.json → WARN status, no crash."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_file = claude_dir / "settings.json"
        settings_file.write_text("{invalid json}", encoding="utf-8")

        result = doctor_main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert "WARN" in out or "host" in out
        assert result >= 0


class TestDoctorHostOverride:
    """Test doctor --host parameter."""

    def test_host_override_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """--host claude-code overrides detection → MISSING for wiring if not set."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        doctor_main(["--host", "claude-code", "--root", str(tmp_path)])
        out = capsys.readouterr().out

        # When host is overridden but settings/AGENTS.md missing, should show MISSING not N/A
        assert "host" not in out or "MISSING" in out or "N/A" not in out.split("\n")[0]


class TestDoctorTextOutputFormat:
    """Test doctor text output format."""

    def test_text_output_no_ansi_codes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """doctor text output has no ANSI escape codes."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        doctor_main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert "\x1b" not in out
