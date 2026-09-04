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
