"""
Tests for workspace_engine.cli.kube.main (orchestrator) and
workspace_engine.cli.kube.tui (interactive Rich pickers).
"""

import importlib
from unittest.mock import MagicMock, patch

kube_main_mod = importlib.import_module("workspace_engine.cli.kube.main")
kube_tui_mod = importlib.import_module("workspace_engine.cli.kube.tui")


# ---------------------------------------------------------------------------
# tui.select_context
# ---------------------------------------------------------------------------


def test_select_context_empty_list_warns_and_returns_none():
    with patch("workspace_engine.cli.kube.tui.log_warning") as mock_warn:
        assert kube_tui_mod.select_context([]) is None
        mock_warn.assert_called_once()


def test_select_context_single_context_returns_directly():
    contexts = [{"name": "ctx-dev", "is_current": True}]
    assert kube_tui_mod.select_context(contexts) == "ctx-dev"


def test_select_context_multiple_prompts_and_returns_choice():
    contexts = [
        {"name": "ctx-dev", "is_current": True},
        {"name": "ctx-prod", "is_current": False},
    ]
    with patch("workspace_engine.cli.kube.tui.Prompt.ask", return_value="2") as mock_ask:
        result = kube_tui_mod.select_context(contexts)
        assert result == "ctx-prod"
        mock_ask.assert_called_once()


# ---------------------------------------------------------------------------
# tui.select_operation
# ---------------------------------------------------------------------------


def test_select_operation_returns_selected_op():
    with patch("workspace_engine.cli.kube.tui.Prompt.ask", return_value="2"):
        assert kube_tui_mod.select_operation() == "logs"


def test_select_operation_default_choice():
    with patch("workspace_engine.cli.kube.tui.Prompt.ask", return_value="1"):
        assert kube_tui_mod.select_operation() == "env"


# ---------------------------------------------------------------------------
# main.handle_env_export
# ---------------------------------------------------------------------------


def test_handle_env_export_prompts_when_no_service_name():
    with (
        patch("workspace_engine.cli.kube.main.Prompt.ask", return_value="auth-service"),
        patch("workspace_engine.cli.kube.main.find_pod", return_value="auth-service-xyz"),
        patch("workspace_engine.cli.kube.main.get_pod_env", return_value={"FOO": "bar"}),
        patch("workspace_engine.cli.kube.main.export_dotenv") as mock_dotenv,
        patch("workspace_engine.cli.kube.main.export_set_env_sh") as mock_sh,
    ):
        rc = kube_main_mod.handle_env_export(None, None)
        assert rc == 0
        mock_dotenv.assert_called_once()
        mock_sh.assert_called_once()


def test_handle_env_export_no_pod_found_returns_1():
    with (
        patch("workspace_engine.cli.kube.main.find_pod", return_value=None),
    ):
        rc = kube_main_mod.handle_env_export("ctx", "svc")
        assert rc == 1


def test_handle_env_export_empty_env_vars_returns_1():
    with (
        patch("workspace_engine.cli.kube.main.find_pod", return_value="svc-pod"),
        patch("workspace_engine.cli.kube.main.get_pod_env", return_value={}),
    ):
        rc = kube_main_mod.handle_env_export("ctx", "svc")
        assert rc == 1


def test_handle_env_export_writes_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with (
        patch("workspace_engine.cli.kube.main.find_pod", return_value="svc-pod"),
        patch("workspace_engine.cli.kube.main.get_pod_env", return_value={"A": "1"}),
        patch("workspace_engine.cli.kube.main.export_dotenv") as mock_dotenv,
        patch("workspace_engine.cli.kube.main.export_set_env_sh") as mock_sh,
    ):
        rc = kube_main_mod.handle_env_export(None, "svc")
        assert rc == 0
        assert mock_dotenv.call_args.args[0] == tmp_path / ".env"
        assert mock_sh.call_args.args[0] == tmp_path / "set-env.sh"


# ---------------------------------------------------------------------------
# main.handle_logs
# ---------------------------------------------------------------------------


def test_handle_logs_prompts_and_uses_pod(monkeypatch):
    with (
        patch("workspace_engine.cli.kube.main.Prompt.ask", return_value="svc"),
        patch("workspace_engine.cli.kube.main.find_pod", return_value="svc-pod"),
        patch("workspace_engine.cli.kube.main.subprocess.run") as mock_run,
    ):
        rc = kube_main_mod.handle_logs("ctx-dev", None)
        assert rc == 0
        cmd = mock_run.call_args.args[0]
        assert "--context" in cmd and "ctx-dev" in cmd
        assert "svc-pod" in cmd


def test_handle_logs_falls_back_to_service_name_when_no_pod():
    with (
        patch("workspace_engine.cli.kube.main.find_pod", return_value=None),
        patch("workspace_engine.cli.kube.main.subprocess.run") as mock_run,
    ):
        rc = kube_main_mod.handle_logs(None, "svc")
        assert rc == 0
        cmd = mock_run.call_args.args[0]
        assert "svc" in cmd
        assert "--context" not in cmd


def test_handle_logs_keyboard_interrupt_returns_0():
    with (
        patch("workspace_engine.cli.kube.main.find_pod", return_value="svc-pod"),
        patch(
            "workspace_engine.cli.kube.main.subprocess.run",
            side_effect=KeyboardInterrupt,
        ),
    ):
        rc = kube_main_mod.handle_logs(None, "svc")
        assert rc == 0


# ---------------------------------------------------------------------------
# main.handle_shell
# ---------------------------------------------------------------------------


def test_handle_shell_prompts_and_returns_returncode():
    mock_result = MagicMock(returncode=3)
    with (
        patch("workspace_engine.cli.kube.main.Prompt.ask", return_value="svc"),
        patch("workspace_engine.cli.kube.main.find_pod", return_value="svc-pod"),
        patch(
            "workspace_engine.cli.kube.main.subprocess.run", return_value=mock_result
        ) as mock_run,
    ):
        rc = kube_main_mod.handle_shell("ctx-dev", None)
        assert rc == 3
        cmd = mock_run.call_args.args[0]
        assert "--context" in cmd and "ctx-dev" in cmd


def test_handle_shell_falls_back_to_service_name_when_no_pod():
    mock_result = MagicMock(returncode=0)
    with (
        patch("workspace_engine.cli.kube.main.find_pod", return_value=None),
        patch(
            "workspace_engine.cli.kube.main.subprocess.run", return_value=mock_result
        ) as mock_run,
    ):
        rc = kube_main_mod.handle_shell(None, "svc")
        assert rc == 0
        cmd = mock_run.call_args.args[0]
        assert "svc" in cmd


def test_handle_shell_keyboard_interrupt_returns_0():
    with (
        patch("workspace_engine.cli.kube.main.find_pod", return_value="svc-pod"),
        patch(
            "workspace_engine.cli.kube.main.subprocess.run",
            side_effect=KeyboardInterrupt,
        ),
    ):
        rc = kube_main_mod.handle_shell(None, "svc")
        assert rc == 0


# ---------------------------------------------------------------------------
# main.main
# ---------------------------------------------------------------------------


def test_main_kubectl_unavailable_returns_1():
    with patch("workspace_engine.cli.kube.main.is_kubectl_available", return_value=False):
        assert kube_main_mod.main("env", "svc") == 1


def test_main_multiple_contexts_selects_via_tui():
    contexts = [{"name": "a", "is_current": True}, {"name": "b", "is_current": False}]
    with (
        patch("workspace_engine.cli.kube.main.is_kubectl_available", return_value=True),
        patch("workspace_engine.cli.kube.main.get_contexts", return_value=contexts),
        patch("workspace_engine.cli.kube.main.select_context", return_value="b") as mock_select,
        patch("workspace_engine.cli.kube.main.handle_env_export", return_value=0) as mock_env,
    ):
        rc = kube_main_mod.main("env", "svc")
        assert rc == 0
        mock_select.assert_called_once_with(contexts)
        mock_env.assert_called_once_with("b", "svc")


def test_main_single_context_used_directly():
    contexts = [{"name": "only-ctx", "is_current": True}]
    with (
        patch("workspace_engine.cli.kube.main.is_kubectl_available", return_value=True),
        patch("workspace_engine.cli.kube.main.get_contexts", return_value=contexts),
        patch("workspace_engine.cli.kube.main.handle_logs", return_value=0) as mock_logs,
    ):
        rc = kube_main_mod.main("logs", "svc")
        assert rc == 0
        mock_logs.assert_called_once_with("only-ctx", "svc")


def test_main_no_action_uses_select_operation():
    with (
        patch("workspace_engine.cli.kube.main.is_kubectl_available", return_value=True),
        patch("workspace_engine.cli.kube.main.get_contexts", return_value=[]),
        patch(
            "workspace_engine.cli.kube.main.select_operation", return_value="shell"
        ) as mock_select_op,
        patch("workspace_engine.cli.kube.main.handle_shell", return_value=0) as mock_shell,
    ):
        rc = kube_main_mod.main(None, "svc")
        assert rc == 0
        mock_select_op.assert_called_once()
        mock_shell.assert_called_once_with(None, "svc")


def test_main_unsupported_operation_returns_1():
    with (
        patch("workspace_engine.cli.kube.main.is_kubectl_available", return_value=True),
        patch("workspace_engine.cli.kube.main.get_contexts", return_value=[]),
    ):
        rc = kube_main_mod.main("bogus", "svc")
        assert rc == 1
