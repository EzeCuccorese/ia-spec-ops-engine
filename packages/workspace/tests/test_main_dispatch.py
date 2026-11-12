"""
Coverage tests for workspace_engine.cli.main: doctor_check's human-readable
branches and the `args.command` dispatch table in main().

The `config` dispatch branch has dedicated coverage in test_ws_cli.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from workspace_engine.cli.main import doctor_check, main

# ---------------------------------------------------------------------------
# doctor_check — human-readable and agent-mode branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("agent_mode", "git_path", "local", "glob", "git_status", "hooks_row"),
    [
        (False, None, False, False, "Not Found", ("Inactive", "ws hooks install --global")),
        (False, "/usr/bin/git", True, False, "Available", ("Active", "(Local)")),
        (True, "/usr/bin/git", False, True, "Available", ("Active", "(Global)")),
        (True, "/usr/bin/git", True, True, "Available", ("Active", "(Local & Global)")),
    ],
    ids=["nothing-found", "local-hooks", "global-hooks", "both-scopes"],
)
def test_doctor_check_rows(agent_mode, git_path, local, glob, git_status, hooks_row):
    hooks_stat = {"local": {"is_active": local}, "global": {"is_active": glob}}
    with (
        patch("workspace_engine.cli.main.is_agent_mode", return_value=agent_mode),
        patch("workspace_engine.cli.main.shutil.which", return_value=git_path),
        patch("workspace_engine.services.git_hooks.get_hooks_status", return_value=hooks_stat),
        patch("workspace_engine.cli.main.emit_rows") as mock_emit,
    ):
        doctor_check()
    rows = {r[0]: r for r in mock_emit.call_args.args[0]}
    assert git_status in rows["git"][1]
    assert hooks_row[0] in rows["git-hooks"][1]
    assert hooks_row[1] in rows["git-hooks"][2]


# ---------------------------------------------------------------------------
# main() — subcommand dispatch table
# ---------------------------------------------------------------------------


def test_main_dispatches_doctor(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sys.argv", ["ws", "doctor"]):
        main()
    out = capsys.readouterr().out
    assert "Development Environment Diagnostics" in out
    assert "git-hooks" in out


def test_main_dispatches_hooks_with_forwarded_args():
    with (
        patch("sys.argv", ["ws", "hooks", "status", "--dir", "/tmp/x"]),
        patch("workspace_engine.cli.manage_hooks.main", return_value=0) as mock_hooks,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    mock_hooks.assert_called_once_with(["status", "--dir", "/tmp/x"])


@pytest.mark.parametrize(
    "command,target",
    [
        ("run", "workspace_engine.condense.cli.run"),
        ("condense", "workspace_engine.condense.cli.condense_stdin"),
        ("log", "workspace_engine.condense.cli.show_log"),
        ("check", "workspace_engine.cli.check.check"),
        ("changed", "workspace_engine.cli.check.changed"),
        ("design", "workspace_engine.cli.design.design"),
    ],
)
def test_main_dispatches_condense_commands(command, target):
    with (
        patch("sys.argv", ["ws", command, "--foo"]),
        patch(target, return_value=0) as mock_handler,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    mock_handler.assert_called_once_with(["--foo"])


def test_main_no_command_prints_help_and_exits_0():
    with (
        patch("sys.argv", ["ws"]),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0


def test_main_version_flag(capsys):
    from workspace_engine import __version__

    with (
        patch("sys.argv", ["ws", "--version"]),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_main_dispatches_detect(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    with (
        patch("sys.argv", ["ws", "detect", "--dir", str(tmp_path)]),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    assert "python" in capsys.readouterr().out

    with (
        patch("sys.argv", ["ws", "detect", "--dir", str(tmp_path), "--json"]),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    assert '"python"' in capsys.readouterr().out
