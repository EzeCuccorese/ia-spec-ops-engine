"""
Coverage tests for workspace_engine.cli.main: doctor_check's human-readable
branches and the full `args.command` dispatch table in main().

The `worktree` and `config` dispatch branches already have dedicated
coverage elsewhere (test_create_worktree.py, test_ws_cli.py) and are not
duplicated here except where needed to complete the parametrized sweep.
"""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest
from workspace_engine.cli.main import doctor_check, main

# ---------------------------------------------------------------------------
# doctor_check — human-readable (non agent-mode) branches
# ---------------------------------------------------------------------------


def test_doctor_check_human_mode_tool_not_found_and_hooks_inactive():
    hooks_stat = {
        "local": {"is_active": False},
        "global": {"is_active": False},
    }
    with (
        patch("workspace_engine.cli.main.is_agent_mode", return_value=False),
        patch("workspace_engine.cli.main.shutil.which", return_value=None),
        patch(
            "workspace_engine.services.git_hooks.get_hooks_status",
            return_value=hooks_stat,
        ),
        patch("workspace_engine.cli.main.emit_rows") as mock_emit,
    ):
        doctor_check()
    rows = mock_emit.call_args.args[0]
    assert any("Not Found" in r[1] for r in rows)
    assert any("Inactive" in r[1] for r in rows)


def test_doctor_check_human_mode_tool_found_and_hooks_active_local_only():
    hooks_stat = {
        "local": {"is_active": True},
        "global": {"is_active": False},
    }
    with (
        patch("workspace_engine.cli.main.is_agent_mode", return_value=False),
        patch("workspace_engine.cli.main.shutil.which", return_value="/usr/bin/git"),
        patch(
            "workspace_engine.services.git_hooks.get_hooks_status",
            return_value=hooks_stat,
        ),
        patch("workspace_engine.cli.main.emit_rows") as mock_emit,
    ):
        doctor_check()
    rows = mock_emit.call_args.args[0]
    assert any("Available" in r[1] for r in rows)
    assert any("Active" in r[1] for r in rows)


def test_doctor_check_hooks_active_global_only():
    hooks_stat = {
        "local": {"is_active": False},
        "global": {"is_active": True},
    }
    with (
        patch("workspace_engine.cli.main.is_agent_mode", return_value=True),
        patch("workspace_engine.cli.main.shutil.which", return_value="/usr/bin/git"),
        patch(
            "workspace_engine.services.git_hooks.get_hooks_status",
            return_value=hooks_stat,
        ),
        patch("workspace_engine.cli.main.emit_rows") as mock_emit,
    ):
        doctor_check()
    rows = mock_emit.call_args.args[0]
    assert any(r[0] == "git-hooks" and r[1] == "Active" for r in rows)


def test_doctor_check_hooks_active_both_scopes():
    hooks_stat = {
        "local": {"is_active": True},
        "global": {"is_active": True},
    }
    with (
        patch("workspace_engine.cli.main.is_agent_mode", return_value=True),
        patch("workspace_engine.cli.main.shutil.which", return_value="/usr/bin/git"),
        patch(
            "workspace_engine.services.git_hooks.get_hooks_status",
            return_value=hooks_stat,
        ),
        patch("workspace_engine.cli.main.emit_rows"),
    ):
        doctor_check()  # exercises the "Local & Global" branch without raising


# ---------------------------------------------------------------------------
# main() — subcommand dispatch table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv,target,expected_call",
    [
        (
            ["ws", "generate", "ws-name", "repo-a"],
            "workspace_engine.cli.generate_workspace.main",
            None,
        ),
        (["ws", "edit", "ws-name"], "workspace_engine.cli.edit_workspace.main", None),
        (["ws", "clean"], "workspace_engine.cli.clean_workspace.main", None),
        (["ws", "stop"], "workspace_engine.cli.stop_workspace.main", None),
        (["ws", "reset"], "workspace_engine.cli.reset_repos.main", None),
        (["ws", "delete", "ws-a"], "workspace_engine.cli.delete_workspaces.main", None),
        (["ws", "build"], "workspace_engine.cli.build_project.main", None),
        (["ws", "deps"], "workspace_engine.cli.install_deps.main", None),
        (["ws", "java"], "workspace_engine.cli.set_java.main", None),
        (["ws", "env-init"], "workspace_engine.cli.init_env.main", None),
        (["ws", "env-load"], "workspace_engine.cli.load_env.main", None),
        (["ws", "benchmark"], "workspace_engine.cli.unit_test_benchmark.main", None),
        (["ws", "run-local"], "workspace_engine.run_local.main.main", None),
    ],
)
def test_main_dispatches_simple_subcommands(argv, target, expected_call):
    with patch("sys.argv", argv), patch(target) as mock_main:
        main()
    mock_main.assert_called_once_with()


def test_main_dispatches_hooks_with_forwarded_args():
    with (
        patch("sys.argv", ["ws", "hooks", "status", "--dir", "/tmp/x"]),
        patch("workspace_engine.cli.manage_hooks.main", return_value=0) as mock_hooks,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    mock_hooks.assert_called_once_with(["status", "--dir", "/tmp/x"])


def test_main_dispatches_hook_claude_worktree_create():
    with (
        patch("sys.argv", ["ws", "hook", "claude-worktree-create", "--repo", "foo"]),
        patch(
            "workspace_engine.integrations.claude.worktree_hook.main", return_value=0
        ) as mock_hook,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    mock_hook.assert_called_once_with(["--repo", "foo"])


def test_main_dispatches_kube_with_action():
    with (
        patch("sys.argv", ["ws", "kube", "env"]),
        patch("workspace_engine.cli.kube.main.main", return_value=0) as mock_kube,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0
    mock_kube.assert_called_once_with("env")


def test_main_dispatches_worktree_with_positional_args():
    with (
        patch("sys.argv", ["ws", "worktree", "repo-a", "/tmp/target", "feature-x"]),
        patch("workspace_engine.cli.create_worktree.main") as mock_wt,
    ):
        main()
    mock_wt.assert_called_once_with(["repo-a", "/tmp/target", "feature-x"])


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


def test_main_dispatches_doctor():
    with (
        patch("sys.argv", ["ws", "doctor"]),
        patch("workspace_engine.cli.main.doctor_check") as mock_doc,
    ):
        main()
    mock_doc.assert_called_once_with()


def test_main_no_command_prints_help_and_exits_0():
    with (
        patch("sys.argv", ["ws"]),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 0


def test_main_hook_with_unsupported_hook_name_is_a_noop():
    """argparse's `choices` restricts `hook_name` to a single known value, so the
    `if args.hook_name == "claude-worktree-create"` false branch is unreachable via
    the real CLI. Exercise it directly with a crafted namespace."""
    fake_args = argparse.Namespace(command="hook", hook_name="unsupported", hook_args=[])
    with (
        patch("sys.argv", ["ws", "hook", "claude-worktree-create"]),
        patch(
            "workspace_engine.cli.main.argparse.ArgumentParser.parse_args",
            return_value=fake_args,
        ),
    ):
        main()  # falls through without raising or dispatching


def test_main_unrecognized_command_is_a_noop():
    """All defined subparsers are handled by the if/elif chain, so a command
    outside that set is unreachable via the real CLI. Exercise the trailing
    fallthrough directly with a crafted namespace."""
    fake_args = argparse.Namespace(command="not-a-real-command")
    with (
        patch("sys.argv", ["ws", "doctor"]),
        patch(
            "workspace_engine.cli.main.argparse.ArgumentParser.parse_args",
            return_value=fake_args,
        ),
    ):
        main()  # falls through without raising or dispatching
