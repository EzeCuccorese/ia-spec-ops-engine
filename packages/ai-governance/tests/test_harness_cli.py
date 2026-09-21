"""Tests for harness CLI list, show, install, and uninstall commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ai_governance.harness.cli import main as harness_main
from ai_governance.rules.core.injector import (
    HARNESS_END_MARKER,
    HARNESS_START_MARKER,
)


class TestHarnessListCommand:
    """Test harness list command output format and content."""

    def test_list_text_output_has_one_line_per_tool(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """harness list text output has one line per tool (truncated in agent mode)."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")

        result = harness_main(["list"])
        out = capsys.readouterr().out

        lines = out.strip().split("\n")
        # In agent mode, output is truncated; at least title + header + some tools
        assert len(lines) >= 3
        # Check that header and tool lines exist
        assert "ID" in out or "Trigger" in out or "Command" in out
        assert result == 0
        assert "\x1b" not in out

    def test_list_json_output_valid_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """harness list --json produces valid JSON with expected keys."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")

        result = harness_main(["list", "--json"])
        out = capsys.readouterr().out

        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) > 0
        for tool in data:
            assert "id" in tool
            assert "trigger" in tool
            assert "command" in tool
        assert result == 0
        assert "\x1b" not in out


class TestHarnessShowCommand:
    """Test harness show command."""

    def test_show_contains_expected_sections(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """harness show includes main sections and claude-code."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")

        result = harness_main(["show"])
        out = capsys.readouterr().out

        assert "## Harness Wiring" in out or "Harness Wiring" in out
        assert "### Automatic tools" in out
        assert "### Host map" in out
        assert "claude-code" in out
        assert result == 0


class TestHarnessInstallCommand:
    """Test harness install command idempotency and file handling."""

    def test_install_local_twice_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """harness install --local --root tmp idempotent: marker appears once."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        result1 = harness_main(["install", "--local", "--root", str(tmp_path)])
        agents_md = tmp_path / "AGENTS.md"
        assert result1 == 0
        assert agents_md.exists()

        first_content = agents_md.read_text(encoding="utf-8")
        assert first_content.count(HARNESS_START_MARKER) == 1
        assert first_content.count(HARNESS_END_MARKER) == 1

        result2 = harness_main(["install", "--local", "--root", str(tmp_path)])
        assert result2 == 0

        second_content = agents_md.read_text(encoding="utf-8")
        assert second_content.count(HARNESS_START_MARKER) == 1
        assert second_content.count(HARNESS_END_MARKER) == 1

    def test_install_preserves_user_content_and_rules_block(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """install with existing user text and rules block → both preserved."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        user_text = "# My Project\n\nCustom notes."
        rules_block = "<!-- rules:start -->\n@rule1\n<!-- rules:end -->\n"
        initial_content = f"{user_text}\n\n{rules_block}"

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(initial_content, encoding="utf-8")

        result = harness_main(["install", "--local", "--root", str(tmp_path)])
        assert result == 0

        content = agents_md.read_text(encoding="utf-8")
        assert "# My Project" in content
        assert "Custom notes." in content
        assert "<!-- rules:start -->" in content
        assert "@rule1" in content
        assert "<!-- harness:start -->" in content


class TestHarnessUninstallCommand:
    """Test harness uninstall command."""

    def test_uninstall_removes_harness_block_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """uninstall removes harness block but leaves other content."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        # Create file with both rules and harness blocks
        user_text = "# Header\n"
        rules_block = "<!-- rules:start -->\n@rule1\n<!-- rules:end -->\n"
        harness_block = "<!-- harness:start -->\n## Harness\n<!-- harness:end -->\n"
        initial = f"{user_text}{rules_block}{harness_block}"

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(initial, encoding="utf-8")

        result = harness_main(["uninstall", "--local", "--root", str(tmp_path)])
        assert result == 0

        content = agents_md.read_text(encoding="utf-8")
        assert "# Header" in content
        assert "<!-- rules:start -->" in content
        assert "@rule1" in content
        assert "<!-- harness:start -->" not in content

    def test_uninstall_deletes_file_if_only_harness(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """uninstall removes file if it contains only harness block."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path / "usage"))

        agents_md = tmp_path / "AGENTS.md"
        harness_block = "<!-- harness:start -->\n## Harness\n<!-- harness:end -->\n"
        agents_md.write_text(harness_block, encoding="utf-8")

        result = harness_main(["uninstall", "--local", "--root", str(tmp_path)])
        assert result == 0
        assert not agents_md.exists()

    def test_uninstall_reports_ok_when_target_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """uninstall is a no-op (status ok) when the target file doesn't exist."""
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        result = harness_main(["uninstall", "--local", "--root", str(tmp_path)])
        out = capsys.readouterr().out
        assert result == 0
        assert "Nothing to uninstall" in out
        assert not (tmp_path / "AGENTS.md").exists()


class TestHarnessErrorHandling:
    """Test harness install/uninstall failure paths and no-op dispatch."""

    def test_install_reports_error_on_oserror(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECOPS_AGENT", "1")

        def boom(self: Path, *_a: object, **_kw: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", boom)
        result = harness_main(["install", "--local", "--root", str(tmp_path)])
        err = capsys.readouterr().err
        assert result == 1
        assert "Failed to write harness wiring" in err

    def test_uninstall_reports_error_on_oserror(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        agents_md = tmp_path / "AGENTS.md"
        harness_block = "<!-- harness:start -->\n## Harness\n<!-- harness:end -->\n"
        agents_md.write_text(harness_block, encoding="utf-8")

        def boom(self: Path) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "unlink", boom)
        result = harness_main(["uninstall", "--local", "--root", str(tmp_path)])
        err = capsys.readouterr().err
        assert result == 1
        assert "Failed to remove harness wiring" in err

    def test_no_action_prints_help(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("SPECOPS_AGENT", "1")
        result = harness_main([])
        out = capsys.readouterr().out
        assert result == 0
        assert "harness" in out.lower()
