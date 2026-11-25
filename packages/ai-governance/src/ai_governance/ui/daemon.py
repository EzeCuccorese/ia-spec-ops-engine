"""PID-file background daemon lifecycle and browser/Orca opener."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path

from ..paths import state_dir
from ..taskflow import orca
from ..taskflow.models import now_iso
from ..taskflow.store import atomic_write_text
from .security import SessionSecurity, validate_loopback_host


@dataclass(frozen=True)
class DaemonInfo:
    pid: int
    host: str
    port: int
    token: str
    started_at: str
    log_path: str

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def ui_state_dir() -> Path:
    return state_dir() / "ui"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clear_state(root: Path) -> None:
    for name in ("server.pid", "server.json"):
        (root / name).unlink(missing_ok=True)


def is_running(root: Path | None = None) -> DaemonInfo | None:
    """Return active daemon metadata, cleaning up stale PID/metadata files if dead."""
    base = root or ui_state_dir()
    meta_path = base / "server.json"
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        info = DaemonInfo(
            pid=int(data["pid"]),
            host=str(data["host"]),
            port=int(data["port"]),
            token=str(data["token"]),
            started_at=str(data.get("started_at", "")),
            log_path=str(data.get("log_path", "")),
        )
    except (OSError, ValueError, KeyError, TypeError):
        _clear_state(base)
        return None
    if not _pid_alive(info.pid):
        _clear_state(base)
        return None
    return info


def _probe_health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.0) as resp:
            return bool(resp.status == 200)
    except (OSError, urllib.error.URLError):
        return False


def _wait_health(host: str, port: int, timeout: float = 10.0) -> bool:
    url = f"http://{host}:{port}/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _probe_health(url):
            return True
        time.sleep(0.15)
    return False


def _write_daemon_state(base: Path, info: DaemonInfo) -> None:
    atomic_write_text(base / "server.pid", f"{info.pid}\n")
    atomic_write_text(base / "server.json", json.dumps(asdict(info), indent=2))


def _spawn_server(host: str, port: int, token: str, log_path: Path) -> subprocess.Popen[bytes]:
    cmd = [
        sys.executable,
        "-m",
        "ai_governance",
        "ui",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--token",
        token,
    ]
    with open(log_path, "a", encoding="utf-8") as log_handle:
        return subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=log_handle,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


def start_daemon(
    host: str = "127.0.0.1",
    port: int = 7474,
    *,
    root: Path | None = None,
) -> DaemonInfo:
    """Start the background UI server and wait for ``/api/health``."""
    clean_host = validate_loopback_host(host)
    base = root or ui_state_dir()
    if existing := is_running(base):
        return existing
    base.mkdir(parents=True, exist_ok=True)
    sec = SessionSecurity.generate(clean_host, port)
    log_path = base / "server.log"
    proc = _spawn_server(clean_host, port, sec.token, log_path)
    if not _wait_health(clean_host, port):
        proc.terminate()
        raise RuntimeError(f"UI server failed to become healthy; check {log_path}")
    info = DaemonInfo(
        pid=proc.pid,
        host=clean_host,
        port=port,
        token=sec.token,
        started_at=now_iso(),
        log_path=str(log_path),
    )
    _write_daemon_state(base, info)
    return info


def stop_daemon(root: Path | None = None) -> bool:
    """Stop the running daemon via SIGTERM (with SIGKILL fallback). Returns True if stopped."""
    base = root or ui_state_dir()
    info = is_running(base)
    if info is None:
        return False
    os.kill(info.pid, signal.SIGTERM)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(info.pid):
            _clear_state(base)
            return True
        time.sleep(0.1)
    os.kill(info.pid, signal.SIGKILL)
    _clear_state(base)
    return True


def open_dashboard(url: str, *, use_orca: bool = False) -> str:
    """Open ``url`` in Orca's embedded browser when requested, else the system web browser."""
    if use_orca or os.environ.get("ORCA_SESSION_ID"):
        argv = [*orca.require_orca(), "browser", "open", url]
        subprocess.run(argv, check=True, capture_output=True, text=True, timeout=15)
        return "orca"
    webbrowser.open(url)
    return "browser"
