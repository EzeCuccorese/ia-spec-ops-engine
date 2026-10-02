"""
Tests for the Kubernetes client and safe env exporter (workspace_engine.cli.kube).
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from workspace_engine.cli.kube.client import (
    find_pod,
    get_contexts,
    get_pod_env,
    is_kubectl_available,
)
from workspace_engine.cli.kube.export import (
    export_dotenv,
    export_set_env_sh,
    write_secret_file,
)


def test_write_secret_file_permissions():
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / ".env.secret"
        write_secret_file(target, "DB_PASS=supersecret\n")

        assert target.exists()
        assert target.read_text() == "DB_PASS=supersecret\n"

        # Verificar permisos 0o600
        mode = os.stat(target).st_mode & 0o777
        assert mode == 0o600


def test_export_dotenv_and_set_env_sh():
    with tempfile.TemporaryDirectory() as tmpdir:
        dotenv_path = Path(tmpdir) / ".env"
        sh_path = Path(tmpdir) / "set-env.sh"

        env_vars = {"PORT": "8080", "DB_HOST": "localhost", "API_KEY": 'abc"123'}
        export_dotenv(dotenv_path, env_vars)
        export_set_env_sh(sh_path, env_vars)

        assert dotenv_path.exists()
        assert "PORT=8080" in dotenv_path.read_text()

        sh_content = sh_path.read_text()
        assert "#!/usr/bin/env bash" in sh_content
        assert 'export PORT="8080"' in sh_content
        assert 'export API_KEY="abc\\"123"' in sh_content


@patch("shutil.which")
def test_is_kubectl_available(mock_which):
    mock_which.return_value = "/usr/local/bin/kubectl"
    assert is_kubectl_available() is True

    mock_which.return_value = None
    assert is_kubectl_available() is False


@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_get_contexts_mock(mock_run):
    mock_run.side_effect = [
        (0, "ctx-dev\nctx-prod\n", ""),  # get-contexts
        (0, "ctx-dev\n", ""),  # current-context
    ]

    with patch("workspace_engine.cli.kube.client.is_kubectl_available", return_value=True):
        contexts = get_contexts()
        assert len(contexts) == 2
        assert contexts[0]["name"] == "ctx-dev"
        assert contexts[0]["is_current"] is True
        assert contexts[1]["name"] == "ctx-prod"
        assert contexts[1]["is_current"] is False


@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_find_pod_mock(mock_run):
    mock_run.return_value = (0, "auth-service-78bfd84c-xyz payment-service-5f899d-abc", "")

    pod = find_pod("auth-service")
    assert pod == "auth-service-78bfd84c-xyz"

    pod_missing = find_pod("users-service")
    assert pod_missing is None


@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_get_pod_env_mock(mock_run):
    mock_run.return_value = (0, "SPRING_PROFILES_ACTIVE=dev\nSERVER_PORT=8081\n", "")

    env_vars = get_pod_env("auth-service-pod")
    assert env_vars["SPRING_PROFILES_ACTIVE"] == "dev"
    assert env_vars["SERVER_PORT"] == "8081"


@patch("workspace_engine.cli.kube.client.is_kubectl_available", return_value=False)
def test_get_contexts_no_kubectl(_mock_available):
    assert get_contexts() == []


@patch("workspace_engine.cli.kube.client.run_command_safe")
@patch("workspace_engine.cli.kube.client.is_kubectl_available", return_value=True)
def test_get_contexts_command_failure(_mock_available, mock_run):
    mock_run.return_value = (1, "", "boom")
    assert get_contexts() == []


@patch("workspace_engine.cli.kube.client.run_command_safe")
@patch("workspace_engine.cli.kube.client.is_kubectl_available", return_value=True)
def test_get_contexts_skips_blank_lines_and_current_lookup_failure(_mock_available, mock_run):
    mock_run.side_effect = [
        (0, "ctx-dev\n\nctx-prod\n", ""),  # get-contexts, includes a blank line
        (1, "", "no current context"),  # current-context lookup fails
    ]
    contexts = get_contexts()
    assert [c["name"] for c in contexts] == ["ctx-dev", "ctx-prod"]
    assert all(c["is_current"] is False for c in contexts)


@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_find_pod_with_context_and_namespace(mock_run):
    mock_run.return_value = (0, "auth-service-abc", "")
    pod = find_pod("auth-service", namespace="staging", context="ctx-dev")
    assert pod == "auth-service-abc"
    cmd = mock_run.call_args.args[0]
    assert "--context" in cmd and "ctx-dev" in cmd
    assert "-n" in cmd and "staging" in cmd


@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_find_pod_command_failure_returns_none(mock_run):
    mock_run.return_value = (1, "", "error")
    assert find_pod("auth-service") is None


@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_get_pod_env_with_context_and_namespace(mock_run):
    mock_run.return_value = (0, "FOO=bar\nnoequalsline\n", "")
    env_vars = get_pod_env("pod-1", namespace="staging", context="ctx-dev")
    assert env_vars == {"FOO": "bar"}
    cmd = mock_run.call_args.args[0]
    assert "--context" in cmd and "ctx-dev" in cmd
    assert "-n" in cmd and "staging" in cmd


@patch("workspace_engine.cli.kube.client.log_warning")
@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_get_pod_env_command_failure_logs_warning(mock_run, mock_warn):
    mock_run.return_value = (1, "", "cannot exec")
    env_vars = get_pod_env("pod-1")
    assert env_vars == {}
    mock_warn.assert_called_once()


@patch("workspace_engine.cli.kube.client.run_command_safe")
def test_get_pod_env_failure_warns_in_english(mock_run, capsys):
    mock_run.return_value = (1, "", "pod not found")

    assert get_pod_env("auth-service-pod") == {}
    assert (
        "Could not read variables from auth-service-pod: pod not found" in capsys.readouterr().out
    )
