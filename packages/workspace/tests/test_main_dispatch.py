"""
Coverage tests for workspace_engine.cli.main: doctor_check's human-readable
branches and the full `args.command` dispatch table in main().

The `config` dispatch branch has dedicated coverage in test_ws_cli.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from workspace_engine.cli.main import doctor_check, main

# ---------------------------------------------------------------------------
# doctor_check — human-readable (non agent-mode) branches
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


@pytest.mark.parametrize(
    "argv,target,forwarded",
    [
        (
            ["ws", "generate", "ws-name", "repo-a"],
            "workspace_engine.cli.generate_workspace.main",
            (),
        ),
        (["ws", "edit", "ws-name"], "workspace_engine.cli.edit_workspace.main", ()),
        (["ws", "clean"], "workspace_engine.cli.clean_workspace.main", ()),
        (["ws", "stop"], "workspace_engine.cli.stop_workspace.main", ()),
        (["ws", "reset"], "workspace_engine.cli.reset_repos.main", ()),
        (["ws", "delete", "ws-a"], "workspace_engine.cli.delete_workspaces.main", ()),
        (["ws", "build"], "workspace_engine.cli.build_project.main", ()),
        (["ws", "deps"], "workspace_engine.cli.install_deps.main", ()),
        (["ws", "java"], "workspace_engine.cli.set_java.main", ()),
        (["ws", "env-init"], "workspace_engine.cli.init_env.main", ()),
        (["ws", "env-load"], "workspace_engine.cli.load_env.main", ()),
        (["ws", "benchmark"], "workspace_engine.cli.unit_test_benchmark.main", ()),
        (["ws", "run-local"], "workspace_engine.run_local.main.main", ()),
        (["ws", "doctor"], "workspace_engine.cli.main.doctor_check", ()),
        (
            ["ws", "worktree", "repo-a", "/tmp/target", "feature-x"],
            "workspace_engine.cli.create_worktree.main",
            (["repo-a", "/tmp/target", "feature-x"],),
        ),
    ],
)
def test_main_dispatches_simple_subcommands(argv, target, forwarded):
    with patch("sys.argv", argv), patch(target) as mock_main:
        main()
    mock_main.assert_called_once_with(*forwarded)


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
