"""Tests for bounded Orca launcher, PID-file daemon lifecycle, and CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from ai_governance.taskflow import orca
from ai_governance.taskflow.dispatch import DispatchError, digest_text, seal_path
from ai_governance.taskflow.models import Task
from ai_governance.taskflow.store import TaskStore
from ai_governance.ui import cli, daemon, launcher


def test_list_live_workers_degrades_gracefully_when_orca_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orca, "_page", lambda _c="": (_ for _ in ()).throw(orca.OrcaError("offline"))
    )
    res = launcher.list_live_workers()
    assert res == {"available": False, "reason": "offline", "workers": []}


def _seed_sealed_round(store: TaskStore, task_id: str) -> tuple[Path, dict[str, object]]:
    store.create(Task(id=task_id, title="Launch test"))
    run_dir = store.task_dir(task_id) / "runs" / "001"
    run_dir.mkdir(parents=True)
    spec = run_dir / "spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    launch_file = run_dir / "launch.json"
    record: dict[str, object] = {
        "task": task_id,
        "n": 1,
        "role": "debater",
        "agent": "codex",
        "model": "gpt-6.2-sol",
        "spec": str(spec),
        "spec_sha": digest_text("# Spec\n"),
        "launch": str(launch_file),
        "argv": ["orca", "worker-start", "--spec", str(spec)],
    }
    body = json.dumps(record, indent=2, sort_keys=True)
    (run_dir / "dispatch.json").write_text(body, encoding="utf-8")
    seal = seal_path(store, task_id, 1)
    seal.parent.mkdir(parents=True, exist_ok=True)
    seal.write_text(digest_text(body), encoding="utf-8")
    return launch_file, record


def test_launch_reserved_round_verifies_seal_and_writes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TaskStore(tmp_path / "tf")
    launch_file, record = _seed_sealed_round(store, "T-L1")
    monkeypatch.setattr(orca, "require_orca", lambda: ["orca"])
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda argv, **_k: subprocess.CompletedProcess(
            argv, 0, stdout='{"ok": true, "result": {"dispatchId": "D-42"}}', stderr=""
        ),
    )

    out = launcher.launch_reserved_round(store, "T-L1", 1)
    assert out["dispatch_id"] == "D-42" and "D-42" in launch_file.read_text(encoding="utf-8")

    record["argv"] = ["rm", "-rf", "/"]
    (store.task_dir("T-L1") / "runs" / "001" / "dispatch.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    with pytest.raises(DispatchError, match="changed after dispatch"):
        launcher.launch_reserved_round(store, "T-L1", 1)


def test_daemon_stale_cleanup_and_open_dashboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "ui"
    state.mkdir(parents=True)
    (state / "server.pid").write_text("999999\n", encoding="utf-8")
    (state / "server.json").write_text(
        json.dumps({"pid": 999999, "host": "127.0.0.1", "port": 7474, "token": "t"}),
        encoding="utf-8",
    )
    assert daemon.is_running(state) is None
    assert not (state / "server.json").exists()

    calls: list[list[str]] = []
    monkeypatch.setattr(orca, "require_orca", lambda: ["orca"])
    monkeypatch.setattr(
        daemon.subprocess,
        "run",
        lambda argv, **_k: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
    )
    assert daemon.open_dashboard("http://127.0.0.1:7474", use_orca=True) == "orca"
    assert calls == [["orca", "browser", "open", "http://127.0.0.1:7474"]]


def test_ui_cli_status_and_invalid_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import ai_governance.__main__ as main_mod

    assert callable(main_mod.main)
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"running": False}
    assert cli.main(["status"]) == 0
    assert cli.main(["stop"]) == 0
    assert cli.main(["open"]) == 1
    assert cli.main(["start", "--host", "0.0.0.0"]) == 2


def test_list_live_workers_success_and_extract_dispatch_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orca,
        "_page",
        lambda _c="": (
            [{"dispatchId": "D-1", "state": "running", "liveness": "alive", "agent": "codex"}],
            None,
        ),
    )
    res = launcher.list_live_workers()
    assert res["available"] is True and res["workers"][0]["dispatch_id"] == "D-1"
    assert launcher._extract_dispatch_id("not-json") == ""
    assert launcher._extract_dispatch_id("[]") == ""
    assert launcher._extract_dispatch_id('{"dispatchId": "D-9"}') == "D-9"
    assert launcher._extract_dispatch_id("{}") == ""


def test_launcher_validation_and_subprocess_error_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TaskStore(tmp_path / "tf")
    _, record = _seed_sealed_round(store, "T-ERR")
    monkeypatch.setattr(orca, "require_orca", lambda: ["orca"])
    with pytest.raises(DispatchError, match="no valid argv"):
        launcher._validate_reserved_argv({"argv": "bad"})
    with pytest.raises(DispatchError, match="sealed Orca"):
        launcher._validate_reserved_argv({"argv": ["orca", "worker-list"]})

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no binary")),
    )
    with pytest.raises(orca.OrcaError, match="Failed to start"):
        launcher.launch_reserved_round(store, "T-ERR", 1)

    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda argv, **_k: subprocess.CompletedProcess(argv, 1, stdout="", stderr="denied"),
    )
    with pytest.raises(orca.OrcaError, match="denied"):
        launcher.launch_reserved_round(store, "T-ERR", 1)

    store.mutate("T-ERR", lambda t: t.rounds.append({"n": 1, "settlement": "collected"}))
    with pytest.raises(DispatchError, match="already settled"):
        launcher.launch_reserved_round(store, "T-ERR", 1)
    assert record["n"] == 1


def test_daemon_health_start_stop_and_browser_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert daemon._pid_alive(0) is False
    monkeypatch.setattr(
        daemon.os, "kill", lambda *_a: (_ for _ in ()).throw(PermissionError("perm"))
    )
    assert daemon._pid_alive(123) is True

    state = tmp_path / "ui"
    state.mkdir()
    (state / "server.json").write_text("{bad", encoding="utf-8")
    assert daemon.is_running(state) is None

    class _FakeResp:
        status = 200

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(daemon.urllib.request, "urlopen", lambda *_a, **_k: _FakeResp())
    assert daemon._probe_health("http://127.0.0.1:7474/api/health") is True
    assert daemon._wait_health("127.0.0.1", 7474, timeout=0.5) is True

    monkeypatch.setattr(
        daemon.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("conn refused")),
    )
    assert daemon._probe_health("http://127.0.0.1:7474/api/health") is False
    assert daemon._wait_health("127.0.0.1", 7474, timeout=0.05) is False

    opened: list[str] = []
    monkeypatch.delenv("ORCA_SESSION_ID", raising=False)
    monkeypatch.setattr(daemon.webbrowser, "open", lambda url: opened.append(url) or True)
    assert daemon.open_dashboard("http://127.0.0.1:7474", use_orca=False) == "browser"
    assert opened == ["http://127.0.0.1:7474"]


def test_daemon_start_and_stop_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "ui"

    class _FakeProc:
        pid = 4242
        terminated = False

        def terminate(self) -> None:
            self.terminated = True

    proc = _FakeProc()
    monkeypatch.setattr(daemon, "_spawn_server", lambda *_a: proc)
    monkeypatch.setattr(daemon, "_wait_health", lambda *_a: False)
    with pytest.raises(RuntimeError, match="failed to become healthy"):
        daemon.start_daemon(root=state)
    assert proc.terminated is True

    monkeypatch.setattr(daemon, "_wait_health", lambda *_a: True)
    monkeypatch.setattr(daemon, "_pid_alive", lambda pid: pid == 4242)
    info = daemon.start_daemon(root=state)
    assert info.pid == 4242 and info.url == "http://127.0.0.1:7474"
    assert daemon.start_daemon(root=state).pid == 4242

    signals: list[int] = []
    alive_checks = iter([True, False])
    monkeypatch.setattr(daemon.os, "kill", lambda _pid, sig: signals.append(sig))
    monkeypatch.setattr(daemon, "_pid_alive", lambda _pid: next(alive_checks, False))
    assert daemon.stop_daemon(state) is True
    assert signals and daemon.stop_daemon(state) is False


def test_daemon_spawn_server_uses_module_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda cmd, **_k: spawned.append(cmd) or object(),
    )
    daemon._spawn_server("127.0.0.1", 7474, "tok", tmp_path / "server.log")
    assert spawned and "serve" in spawned[0]


def test_ui_cli_start_serve_status_stop_and_open_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AI_GOVERNANCE_STATE_DIR", str(tmp_path / "state"))
    info = daemon.DaemonInfo(101, "127.0.0.1", 7474, "tok", "2026-01-01T00:00:00Z", "log")
    monkeypatch.setattr(cli, "start_daemon", lambda **_k: info)
    monkeypatch.setattr(cli, "is_running", lambda: info)
    monkeypatch.setattr(cli, "stop_daemon", lambda: True)
    monkeypatch.setattr(cli, "open_dashboard", lambda *_a, **_k: "orca")
    served: list[tuple[str, int]] = []
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda _app, host, port, **_k: served.append((host, port))
    )

    assert cli.main(["start", "--background"]) == 0
    assert cli.main(["start", "--port", "7475"]) == 0
    assert cli.main(["serve", "--token", "abc"]) == 0
    assert cli.main(["serve"]) == 0
    capsys.readouterr()
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pid"] == 101
    assert cli.main(["status"]) == 0
    assert cli.main(["open", "--orca"]) == 0
    assert cli.main(["stop"]) == 0
    assert len(served) == 3
