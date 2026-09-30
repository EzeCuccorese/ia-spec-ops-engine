"""
Additional coverage-focused unit tests for workspace_engine.run_local.process_manager,
covering health probing, log rotation, RAM accounting, env dumping, port checks,
env fetching, launching, and state persistence — all with mocked subprocess/socket/psutil
so no real long-running process is spawned.
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from workspace_engine.run_local import process_manager as pm


def test_probe_one_port_closed_sets_starting() -> None:
    pm._HEALTH.clear()
    with patch("socket.create_connection", side_effect=OSError("refused")):
        pm._probe_one("svc", 65000, "node")
    assert pm._HEALTH["svc"] == "starting"


def test_probe_one_non_spring_sets_up() -> None:
    pm._HEALTH.clear()
    with patch("socket.create_connection"):
        pm._probe_one("svc", 65000, "node")
    assert pm._HEALTH["svc"] == "up"


@pytest.mark.parametrize(
    ("body", "service_type", "expected"),
    [
        (b'{"status": "UP"}', "spring-gradle", "up"),
        (b'{"status": "DOWN"}', "spring-maven", "unhealthy"),
    ],
)
def test_probe_one_spring_health_endpoint(body: bytes, service_type: str, expected: str) -> None:
    pm._HEALTH.clear()
    fake_resp = MagicMock()
    fake_resp.read.return_value = body
    fake_resp.__enter__.return_value = fake_resp
    with (
        patch("socket.create_connection"),
        patch("urllib.request.urlopen", return_value=fake_resp),
    ):
        pm._probe_one("svc", 65000, service_type)
    assert pm._HEALTH["svc"] == expected


def test_probe_one_spring_health_endpoint_error_falls_back_up() -> None:
    pm._HEALTH.clear()
    with (
        patch("socket.create_connection"),
        patch("urllib.request.urlopen", side_effect=OSError("timeout")),
    ):
        pm._probe_one("svc", 65000, "spring-gradle")
    assert pm._HEALTH["svc"] == "up"


def test_health_worker_removes_dead_and_probes_alive() -> None:
    pm._HEALTH.clear()
    results = [
        {"name": "svc-alive", "pid": 1, "port": 1234, "type": "node"},
        {"name": "svc-dead", "pid": 2, "port": 1235, "type": "node"},
    ]
    pm._HEALTH["svc-dead"] = "up"
    stop_event = threading.Event()

    call_count = {"n": 0}

    def fake_pid_alive(pid: int | None) -> bool:
        call_count["n"] += 1
        if call_count["n"] > 1:
            stop_event.set()
        return pid == 1

    with (
        patch.object(pm, "_pid_alive", side_effect=fake_pid_alive),
        patch("socket.create_connection"),
    ):
        pm._health_worker(results, stop_event)

    assert pm._HEALTH == {"svc-alive": "up"}


@pytest.mark.parametrize(
    ("health", "expected"),
    [("up", "● up"), ("starting", "◐ starting"), ("unhealthy", "✖ unhealthy"), (None, "● running")],
)
def test_status_str_reflects_health(health: str | None, expected: str) -> None:
    pm._HEALTH.pop("svc", None)
    if health:
        pm._HEALTH["svc"] = health
    with patch.object(pm, "_pid_alive", return_value=True):
        plain, _ = pm._status_str("svc", 123)
    pm._HEALTH.pop("svc", None)
    assert plain == expected


def test_log_rotation_worker_rotates_large_file(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_file = logs_dir / "svc.log"
    log_file.write_bytes(b"x" * 100)

    stop_event = threading.Event()

    call_count = {"n": 0}
    real_wait = stop_event.wait

    def fake_wait(timeout: float) -> bool:
        call_count["n"] += 1
        if call_count["n"] >= 2:
            stop_event.set()
        return real_wait(0)

    with (
        patch.object(pm.constants, "LOGS_DIR", logs_dir),
        patch.object(pm.constants, "LOG_MAX_BYTES", 10),
        patch.object(pm.constants, "LOG_KEEP_BYTES", 5),
        patch.object(stop_event, "wait", side_effect=fake_wait),
    ):
        pm._log_rotation_worker(stop_event)

    content = log_file.read_bytes()
    assert b"log rotated" in content
    assert content.endswith(b"x" * 5)


def test_all_group_rss_empty_list() -> None:
    assert pm._all_group_rss([]) == {}


def test_all_group_rss_via_ps() -> None:
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="123 456 2048\n789 999 1024\n", stderr=""
    )
    with patch("subprocess.run", return_value=fake):
        totals = pm._all_group_rss([123, 789])
    assert totals[123] == 2048
    assert totals[789] == 1024


def test_all_group_rss_fallback_to_os_kill() -> None:
    with (
        patch("subprocess.run", side_effect=OSError("no ps")),
        patch("os.kill", return_value=None),
    ):
        totals = pm._all_group_rss([555])
    assert totals[555] == 1024


def test_save_env_dump_writes_file(tmp_path: Path) -> None:
    envs_dir = tmp_path / "envs"
    with patch.object(pm.constants, "ENVS_DIR", envs_dir):
        pm._save_env_dump("svc", {"FOO": "bar"}, "local", "local", "auto")
    dump = envs_dir / "svc.env"
    assert dump.exists()
    assert "FOO=bar" in dump.read_text(encoding="utf-8")


def test_port_in_use_free_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    # Port is free again after the socket closed above.
    assert pm._port_in_use(free_port) is None


def test_port_in_use_occupied_port_reports_owner() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupying:
        occupying.bind(("127.0.0.1", 0))
        occupying.listen(1)
        port = occupying.getsockname()[1]

        fake_lsof = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="COMMAND PID\nnode 4242\n",
            stderr="",
        )
        with patch("subprocess.run", return_value=fake_lsof):
            result = pm._port_in_use(port)
        assert result == "node (PID 4242)"


def test_port_in_use_occupied_lsof_fails() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupying:
        occupying.bind(("127.0.0.1", 0))
        occupying.listen(1)
        port = occupying.getsockname()[1]
        with patch("subprocess.run", side_effect=OSError("no lsof")):
            result = pm._port_in_use(port)
        assert result == "unknown process"


def test_wait_port_free_returns_true_immediately() -> None:
    with patch.object(pm, "_port_in_use", return_value=None):
        assert pm._wait_port_free(1234, timeout=1.0) is True


def test_wait_port_free_times_out() -> None:
    with patch.object(pm, "_port_in_use", return_value="busy"):
        assert pm._wait_port_free(1234, timeout=0.05) is False


def test_env_by_id_found_and_missing() -> None:
    with patch.object(pm.constants, "ENVIRONMENTS", [{"id": "local"}, {"id": "dev"}]):
        assert pm._env_by_id("dev") == {"id": "dev"}
        assert pm._env_by_id("missing") is None


def test_fetch_env_for_local(tmp_path: Path) -> None:
    cfg = {"path": tmp_path, "name": "svc"}
    with (
        patch.object(pm, "resolve_local_env", return_value=tmp_path / "set-env-local.sh"),
        patch.object(pm, "parse_set_env_sh", return_value={"FOO": "bar"}),
    ):
        result = pm.fetch_env_for(cfg, "local")
    assert result == {"FOO": "bar"}


def test_fetch_env_for_local_no_file(tmp_path: Path) -> None:
    cfg = {"path": tmp_path, "name": "svc"}
    with patch.object(pm, "resolve_local_env", return_value=None):
        assert pm.fetch_env_for(cfg, "local") == {}


def test_fetch_env_for_pod_env_cached() -> None:
    pm._POD_ENV_CACHE.clear()
    pm._POD_ENV_CACHE[("svc", "dev")] = {"CACHED": "1"}
    cfg = {"name": "svc"}
    assert pm.fetch_env_for(cfg, "dev") == {"CACHED": "1"}
    pm._POD_ENV_CACHE.clear()


def test_fetch_env_for_pod_env_fetches_and_caches() -> None:
    pm._POD_ENV_CACHE.clear()
    cfg = {"name": "svc"}
    with (
        patch.object(pm, "_env_by_id", return_value={"cluster": "dev", "namespace": "ns"}),
        patch.object(pm, "_resolve_context", return_value="dev-ctx"),
        patch.object(pm, "find_pod", return_value=("pod-1", None)),
        patch.object(pm, "get_pod_env", return_value={"X": "1"}),
    ):
        result = pm.fetch_env_for(cfg, "dev")
    assert result == {"X": "1"}
    assert pm._POD_ENV_CACHE[("svc", "dev")] == {"X": "1"}
    pm._POD_ENV_CACHE.clear()


def test_launch_one_port_occupied() -> None:
    cfg = {
        "name": "svc",
        "path": Path("/tmp/svc"),
        "port": 4000,
        "env": {"id": "local"},
        "service": {"type": "node", "cmd": ["npm", "start"], "port_var": "PORT"},
    }
    with patch.object(pm, "_port_in_use", return_value="node (PID 1)"):
        pid, err, started_at, wiring = pm._launch_one(cfg, {}, {})
    assert pid is None
    assert "occupied" in err
    assert started_at is None
    assert wiring == {}


def test_launch_one_success_local(tmp_path: Path) -> None:
    cfg = {
        "name": "svc",
        "path": tmp_path,
        "port": 4000,
        "env": {"id": "local"},
        "service": {"type": "node", "cmd": ["npm", "start"], "port_var": "PORT"},
        "up_mode": "auto",
    }
    fake_proc = MagicMock()
    fake_proc.pid = 4242
    with (
        patch.object(pm, "_port_in_use", return_value=None),
        patch.object(pm, "resolve_local_env", return_value=None),
        patch.object(pm, "wire_urls", return_value=({"PORT": "4000"}, {})),
        patch.object(pm.constants, "LOGS_DIR", tmp_path / "logs"),
        patch.object(pm.constants, "PIDS_DIR", tmp_path / "pids"),
        patch("subprocess.Popen", return_value=fake_proc),
    ):
        pid, err, started_at, wiring = pm._launch_one(cfg, {"svc": 4000}, {})
    assert pid == 4242
    assert err is None
    assert started_at is not None
    assert (tmp_path / "pids" / "svc.pid").exists()


def test_launch_one_popen_failure(tmp_path: Path) -> None:
    cfg = {
        "name": "svc",
        "path": tmp_path,
        "port": 4000,
        "env": {"id": "local"},
        "service": {"type": "node", "cmd": ["npm", "start"], "port_var": "PORT"},
        "up_mode": "auto",
    }
    with (
        patch.object(pm, "_port_in_use", return_value=None),
        patch.object(pm, "resolve_local_env", return_value=None),
        patch.object(pm, "wire_urls", return_value=({"PORT": "4000"}, {})),
        patch.object(pm.constants, "LOGS_DIR", tmp_path / "logs"),
        patch.object(pm.constants, "PIDS_DIR", tmp_path / "pids"),
        patch("subprocess.Popen", side_effect=OSError("cannot exec")),
    ):
        pid, err, started_at, wiring = pm._launch_one(cfg, {"svc": 4000}, {})
    assert pid is None
    assert "cannot exec" in err
    assert started_at is None


def test_launch_services_reports_results(tmp_path: Path) -> None:
    cfg = {
        "name": "svc",
        "path": tmp_path,
        "port": 4000,
        "env": {"id": "local"},
        "service": {"type": "node", "cmd": ["npm", "start"], "port_var": "PORT"},
    }
    with patch.object(pm, "_launch_one", return_value=(1234, None, 1000.0, {})):
        results, configs = pm.launch_services([cfg], {})
    assert results[0]["pid"] == 1234
    assert results[0]["ok"] is True
    assert configs[0]["wiring"] == {}


def test_load_state_no_file() -> None:
    with patch.object(pm.constants, "STATE_FILE", Path("/nonexistent/state.json")):
        results, configs = pm.load_state()
    assert results == []
    assert configs == []


def test_load_state_invalid_json(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text("{not valid", encoding="utf-8")
    with patch.object(pm.constants, "STATE_FILE", state_file):
        results, configs = pm.load_state()
    assert results == []
    assert configs == []


def test_load_state_filters_dead_pids(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    entries = [
        {
            "name": "svc-dead",
            "path": str(tmp_path),
            "pid": 99999999,
            "port": 4000,
            "base_env": "local",
        },
        {
            "name": "svc-alive",
            "path": str(tmp_path),
            "pid": 1,
            "port": 4001,
            "base_env": "local",
            "type": "node",
        },
    ]
    state_file.write_text(json.dumps(entries), encoding="utf-8")
    with (
        patch.object(pm.constants, "STATE_FILE", state_file),
        patch.object(pm.constants, "ENVIRONMENTS", [{"id": "local"}]),
        patch.object(pm.constants, "LOCAL_ENV", {"id": "local"}),
        patch.object(pm, "detect_service", return_value=None),
    ):
        results, configs = pm.load_state()
    assert len(results) == 1
    assert results[0]["name"] == "svc-alive"
    assert configs[0]["service"]["type"] == "node"
