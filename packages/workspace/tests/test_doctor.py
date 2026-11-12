from __future__ import annotations

import pytest
from workspace_engine.cli import main
from workspace_engine.services import git_hooks


def _hooks_status(*, local: bool, global_: bool) -> dict[str, dict[str, bool]]:
    return {
        "local": {"is_active": local},
        "global": {"is_active": global_},
    }


@pytest.mark.parametrize("agent_mode", [True, False], ids=["agent", "human"])
def test_doctor_check_tool_discovery_matrix(
    monkeypatch, capsys, agent_mode: bool
) -> None:
    available_symbol = "Available" if agent_mode else "✓ Available"
    missing_symbol = "Not Found" if agent_mode else "⚠ Not Found"
    present = {"git": "/usr/bin/git", "uv": "/opt/bin/uv"}
    monkeypatch.setattr(main, "is_agent_mode", lambda: agent_mode)
    monkeypatch.setattr(main.shutil, "which", lambda tool: present.get(tool))
    monkeypatch.setattr(git_hooks, "get_hooks_status", lambda: _hooks_status(local=False, global_=False))

    main.doctor_check()
    out = capsys.readouterr().out

    assert "Development Environment Diagnostics (ws doctor)" in out
    assert f"git | {available_symbol} | Git Version Control (/usr/bin/git)" in out
    assert f"uv | {available_symbol} | Fast Python Package Manager (/opt/bin/uv)" in out
    for missing in ("kubectl", "java", "mvn", "node", "npm", "docker"):
        assert f"{missing} | {missing_symbol} | " in out


@pytest.mark.parametrize(
    "case",
    [
        (
            False,
            False,
            True,
            "git-hooks | Inactive | Run 'ws hooks install --global' to protect git push",
        ),
        (
            False,
            False,
            False,
            "git-hooks | ⚠ Inactive | Run 'ws hooks install --global' to protect git push",
        ),
        (True, False, True, "git-hooks | Active | Pre-Push Quality Gate (Local)"),
        (False, True, True, "git-hooks | Active | Pre-Push Quality Gate (Global)"),
        (True, True, True, "git-hooks | Active | Pre-Push Quality Gate (Local & Global)"),
        (True, True, False, "git-hooks | ✓ Active | Pre-Push Quality Gate (Local & Global)"),
    ],
)
def test_doctor_check_hooks_matrix(
    monkeypatch,
    capsys,
    case: tuple[bool, bool, bool, str],
) -> None:
    local, global_, agent_mode, expected_row = case
    monkeypatch.setattr(main, "is_agent_mode", lambda: agent_mode)
    monkeypatch.setattr(main.shutil, "which", lambda _tool: None)
    monkeypatch.setattr(
        git_hooks, "get_hooks_status", lambda: _hooks_status(local=local, global_=global_)
    )

    main.doctor_check()
    out = capsys.readouterr().out

    assert expected_row in out
