"""Coverage tests for ai_governance.harness.doctor edge cases and helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ai_governance.harness import doctor
from ai_governance.rules.core.catalog import ToolDefinition


def _tool(trigger: str, command: str = "frugal --pre-bash") -> ToolDefinition:
    return ToolDefinition(
        id="fake-tool",
        package="fake-pkg",
        command=command,
        purpose="testing",
        trigger=trigger,
        io_stdin="",
        io_stdout="",
        replaces=(),
        fail_mode="fail-open",
    )


class _FakeCatalog:
    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._tools = tools

    def automatic_tools(self) -> list[ToolDefinition]:
        return self._tools


def test_hook_commands_returns_empty_when_hooks_not_dict() -> None:
    assert doctor._hook_commands({"hooks": "not-a-dict"}, "PreToolUse") == []


def test_hook_commands_returns_empty_when_entries_not_list() -> None:
    assert doctor._hook_commands({"hooks": {"PreToolUse": "not-a-list"}}, "PreToolUse") == []


def test_hook_commands_skips_non_dict_entries() -> None:
    settings = {"hooks": {"PreToolUse": ["not-a-dict", {"hooks": [{"command": "x"}]}]}}
    assert doctor._hook_commands(settings, "PreToolUse") == ["x"]


def test_hook_commands_skips_entry_with_mismatched_matcher() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Other", "hooks": [{"command": "should-not-appear"}]},
                {"matcher": "Bash", "hooks": [{"command": "matches"}]},
            ]
        }
    }
    result = doctor._hook_commands(settings, "PreToolUse", matcher="Bash")
    assert result == ["matches"]


def test_hook_commands_skips_entry_with_non_list_hooks() -> None:
    settings = {"hooks": {"PreToolUse": [{"hooks": "not-a-list"}]}}
    assert doctor._hook_commands(settings, "PreToolUse") == []


def test_hook_commands_skips_non_dict_hook_items() -> None:
    settings = {"hooks": {"PreToolUse": [{"hooks": ["not-a-dict", {"command": "kept"}]}]}}
    assert doctor._hook_commands(settings, "PreToolUse") == ["kept"]


def test_hook_commands_skips_hooks_with_non_str_command() -> None:
    settings = {"hooks": {"PreToolUse": [{"hooks": [{"command": 123}, {"command": "kept"}]}]}}
    assert doctor._hook_commands(settings, "PreToolUse") == ["kept"]


def test_binding_satisfied_returns_false_for_unknown_trigger() -> None:
    tool = _tool("unknown-trigger")
    assert doctor._binding_satisfied({}, tool, "unknown-trigger") is False


def test_host_wiring_checks_parse_failed_when_json_is_a_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A settings.json that parses to a non-dict (e.g. a list) sets parse_failed."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("[1, 2, 3]", encoding="utf-8")

    catalog = _FakeCatalog([_tool("before-shell-command")])
    checks = doctor._host_wiring_checks(catalog, "claude-code")
    assert checks == [("WARN", "host:before-shell-command", checks[0][2])]


def test_host_wiring_checks_skips_tools_without_a_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A tool trigger with no entry in the host's bindings is skipped."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    catalog = _FakeCatalog([_tool("no-such-trigger")])
    checks = doctor._host_wiring_checks(catalog, "claude-code")
    assert checks == []


def test_runtime_dir_check_warns_when_not_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SPECOPS_USAGE_DIR", str(tmp_path))
    monkeypatch.setattr(os, "access", lambda *_a, **_kw: False)
    status, name, hint = doctor._runtime_dir_check()
    assert status == "WARN"
    assert name == "runtime-dir"
    assert "not writable" in hint
