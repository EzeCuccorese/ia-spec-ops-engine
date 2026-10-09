from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from ai_governance import hooks
from ai_governance.install import probe
from ai_governance.install.installer import install_user, uninstall_user


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("CODEX_HOME", raising=False)


def _fire(monkeypatch, agent: str, event: str, payload: dict) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    probe.record(agent, event)


def test_probe_builds_canaries_and_recording_hooks(tmp_path: Path) -> None:
    root = probe.build("antigravity", tmp_path / "p")
    assert "CANARY-AG-GLOB" in (root / ".agents/rules/probe-glob.md").read_text()
    config = json.loads((root / ".agents/hooks.json").read_text())["ai-governance-probe"]
    assert set(config) == set(probe.EVENTS)
    assert config["PreToolUse"][0]["matcher"] == "*" and "command" in config["Stop"][0]
    claude = probe.build("claude", tmp_path / "c")
    link = claude / ".claude/rules/probe-dual.md"
    assert link.is_symlink() and "CANARY-CLAUDE-LINK" in link.read_text()
    assert "CANARY-AG-DUAL" in (root / ".agents/rules/probe-dual.md").read_text()


def test_codex_hooks_install_only_after_verified_probe(monkeypatch, tmp_path: Path) -> None:
    install_user(["codex"])
    assert not (tmp_path / "home/.codex/hooks.json").exists()

    probe.build("codex", tmp_path / "p")
    shell = {"tool_input": {"command": "echo probe"}, "tool_response": {"stdout": "probe"}}
    _fire(monkeypatch, "codex", "PreToolUse", shell)
    _fire(monkeypatch, "codex", "PostToolUse", shell)
    result = probe.verify("codex", ["CANARY-AGENTS-MD"])
    assert result["shell_hooks_verified"] and result["canaries_missing"] == [
        "CANARY-CODEX-NESTED",
        "CANARY-SCOUT",
    ]

    install_user(["codex"])
    data = json.loads((tmp_path / "home/.codex/hooks.json").read_text())
    assert data["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == (
        "ai-governance hook codex post-tool-use"
    )
    assert 'model = "terra"' in (tmp_path / "home/.codex/agents/scout.toml").read_text()


def test_antigravity_hook_installs_as_named_group_after_pre_tool_probe(
    monkeypatch, tmp_path: Path
) -> None:
    hooks_path = tmp_path / "home/.gemini/config/hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(json.dumps({"other": {"Stop": [{"command": "x"}]}}))
    probe.build("antigravity", tmp_path / "p")
    call = {"toolCall": {"name": "run_command", "args": {"CommandLine": "echo probe"}}}
    _fire(monkeypatch, "antigravity", "PreToolUse", call)
    _fire(monkeypatch, "antigravity", "PostToolUse", {"stepIdx": 1})
    assert probe.verify("antigravity", [])["shell_hooks_verified"] is True

    install_user(["antigravity"])
    data = json.loads(hooks_path.read_text())
    assert data["other"] == {"Stop": [{"command": "x"}]}
    assert data["ai-governance"]["PreToolUse"] == [
        {
            "matcher": "run_command",
            "hooks": [
                {"type": "command", "command": "ai-governance hook antigravity pre-tool-use"}
            ],
        }
    ]
    uninstall_user(["antigravity"])
    assert json.loads(hooks_path.read_text()) == {"other": {"Stop": [{"command": "x"}]}}


def test_unverified_when_hooks_never_fired() -> None:
    assert probe.verify("antigravity", [])["shell_hooks_verified"] is False
    assert probe.shell_hooks_verified("antigravity") is False


def test_codex_post_hook_blocks_with_condensed_reason(monkeypatch, capsys) -> None:
    from ai_governance.frugality import cli as frugal

    monkeypatch.setattr(frugal, "condensed_output", lambda payload, cfg: ("summary", "summary"))
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert hooks.main(["codex", "post-tool-use"]) == 0
    assert json.loads(capsys.readouterr().out) == {"decision": "block", "reason": "summary"}


@pytest.mark.parametrize(
    ("command", "denied"),
    [
        ("pytest -q", True),
        ("./gradlew test", True),
        ("ws run -- pytest", False),
        ("git diff", False),
        ("ls -la", False),
        ("pytest #nofrugal", False),
    ],
)
def test_antigravity_pre_hook_redirects_noisy_commands(
    monkeypatch, capsys, command, denied
) -> None:
    call = {"toolCall": {"name": "run_command", "args": {"CommandLine": command}}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(call)))
    assert hooks.main(["antigravity", "pre-tool-use"]) == 0
    out = capsys.readouterr().out
    if denied:
        payload = json.loads(out)
        assert payload["decision"] == "deny" and f"ws run -- {command}" in payload["reason"]
    else:
        assert out == ""
