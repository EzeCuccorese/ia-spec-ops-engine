"""
Tests unitarios exhaustivos para workspace_engine.run_local.process_manager.
Cubre verificación de procesos vivos, escalado de señales, guardado y carga de estado,
manejo de puertos y terminación elegante.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from workspace_engine.run_local.process_manager import (
    _pid_alive,
    _status_str,
    graceful_kill_pid,
    save_state,
    stop_all,
)


def test_pid_alive_current_process():
    current_pid = os.getpid()
    assert _pid_alive(current_pid) is True
    assert _pid_alive(99999999) is False  # PID inexistente


def test_status_str():
    plain, colored = _status_str("svc-test", 99999999)
    assert "stopped" in plain
    assert "stopped" in colored


def test_save_and_load_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        state_file = tmp_path / "state.json"
        data_dir = tmp_path

        with (
            patch("workspace_engine.run_local.constants.STATE_FILE", state_file),
            patch("workspace_engine.run_local.constants.DATA_DIR", data_dir),
        ):
            mock_launch = [
                {
                    "name": "svc-a",
                    "path": str(tmp_path),
                    "port": 8080,
                    "env": {},
                    "base_env": "local",
                    "db_env": "local",
                    "up_mode": "auto",
                }
            ]
            mock_results = [
                {
                    "name": "svc-a",
                    "path": str(tmp_path),
                    "port": 8080,
                    "pid": os.getpid(),
                    "ok": True,
                    "type": "node",
                }
            ]

            save_state(mock_launch, mock_results)
            assert state_file.exists()


def test_graceful_kill_pid_already_dead():
    # Matar un PID inexistente debe ser no-op sin lanzar excepción
    graceful_kill_pid(99999999, timeout=0.1)


@patch("os.kill")
def test_graceful_kill_pid_escalation(mock_kill):
    # Simular que el proceso no muere con SIGTERM y requiere SIGKILL
    with patch(
        "workspace_engine.run_local.process_manager._pid_alive",
        side_effect=[True, True, True, False],
    ):
        graceful_kill_pid(12345, timeout=0.1)

        # Verificar que se llamó a SIGTERM (15) y luego a SIGKILL (9)
        calls = mock_kill.call_args_list
        signals_sent = [call[0][1] for call in calls]
        assert 15 in signals_sent
        assert 9 in signals_sent


def test_stop_all_clean_pids():
    with tempfile.TemporaryDirectory() as tmpdir:
        pids_dir = Path(tmpdir) / "pids"
        pids_dir.mkdir()
        state_file = Path(tmpdir) / "state.json"
        state_file.touch()

        # Crear archivos pid falsos
        (pids_dir / "service1.pid").write_text("99999991\n")
        (pids_dir / "service2.pid").write_text("99999992\n")

        with (
            patch("workspace_engine.run_local.constants.PIDS_DIR", pids_dir),
            patch("workspace_engine.run_local.constants.STATE_FILE", state_file),
            patch("workspace_engine.run_local.process_manager.graceful_kill_pid") as mock_kill,
        ):
            stop_all()
            assert mock_kill.call_count == 2
            # Los archivos .pid y state.json deben haberse borrado
            assert len(list(pids_dir.glob("*.pid"))) == 0
            assert not state_file.exists()


@patch("os.kill")
def test_graceful_kill_pid_safety_guards(mock_kill):
    """Rechazar inmediatamente pids <= 1 o pid del proceso actual sin enviar señales."""
    graceful_kill_pid(0)
    graceful_kill_pid(1)
    graceful_kill_pid(os.getpid())
    mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_pid_reuse_prevention(mock_kill):
    """W05: Proteger contra PID reutilizado por un proceso ajeno al servicio."""
    with patch(
        "workspace_engine.utils.get_process_cmdline",
        return_value="postgres: background worker",
    ):
        graceful_kill_pid(12345, service_name="auth-service")
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_does_not_kill_own_group(mock_kill):
    """No enviar señal a -pid si pid coincide con el grupo del proceso actual."""
    current_pgid = os.getpgrp()
    with (
        patch("workspace_engine.run_local.process_manager._pid_alive", return_value=False),
        patch("os.getpid", return_value=99999),  # diferente al pid testeado
    ):
        stopped = graceful_kill_pid(current_pgid)
        # Verify that os.kill was NOT called with -current_pgid
        for call in mock_kill.call_args_list:
            assert call[0][0] != -current_pgid
        assert stopped is True


@patch("os.kill")
def test_graceful_kill_pid_rejects_disallowed_tools(mock_kill):
    """Rechazar procesos de herramientas como grep, cat o vim que contienen el nombre del servicio como argumento."""
    with patch(
        "workspace_engine.utils.get_process_cmdline",
        return_value="grep -r auth-service .",
    ):
        stopped = graceful_kill_pid(12345, service_name="auth-service")
        assert stopped is False
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_rejects_foreign_workspace_matching_service_name(mock_kill):
    """Verifica que si la ruta del servicio (service_path) no coincide con cmdline,

    NO se acepte el proceso aunque service_name coincida en otro workspace
    (e.g. buscando proyecto-a/api contra node /workspaces/proyecto-b/api/server.js).
    """
    with patch(
        "workspace_engine.utils.get_process_cmdline",
        return_value="node /workspaces/proyecto-b/api/server.js",
    ):
        # Buscando proyecto-a/api con service_name="api" y service_path="proyecto-a/api"
        stopped = graceful_kill_pid(
            12345,
            service_name="api",
            service_path="proyecto-a/api",
        )
        assert stopped is False
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_rejects_foreign_workspace_when_service_name_has_path(mock_kill):
    """Verifica que si service_name incluye ruta (e.g. 'proyecto-a/api'),

    se rechace si cmdline apunta a otro workspace ('proyecto-b/api').
    """
    with patch(
        "workspace_engine.utils.get_process_cmdline",
        return_value="node /workspaces/proyecto-b/api/server.js",
    ):
        stopped = graceful_kill_pid(
            12345,
            service_name="proyecto-a/api",
        )
        assert stopped is False
        mock_kill.assert_not_called()


@patch("os.kill")
def test_graceful_kill_pid_accepts_matching_service_path(mock_kill):
    """Verifica que si service_path coincide en cmdline, el proceso es aceptado."""
    with (
        patch(
            "workspace_engine.utils.get_process_cmdline",
            return_value="node /workspaces/proyecto-a/api/server.js",
        ),
        patch("workspace_engine.run_local.process_manager._pid_alive", return_value=False),
    ):
        stopped = graceful_kill_pid(
            12345,
            service_name="api",
            service_path="proyecto-a/api",
        )
        assert stopped is True
        mock_kill.assert_called()
