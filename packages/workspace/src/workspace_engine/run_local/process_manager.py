"""
workspace_engine.run_local.process_manager — Process execution, health probes, PID management, and persistence.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from workspace_engine.run_local import constants
from workspace_engine.run_local.constants import (
    BOLD,
    GREEN,
    RED,
    RESET,
    YELLOW,
)
from workspace_engine.run_local.discovery import (
    _db_vars_from,
    _is_noise,
    _parse_dotenv,
    _resolve_context,
    detect_service,
    find_pod,
    get_pod_env,
    override_urls_from_env,
    parse_app_vars,
    parse_set_env_sh,
    resolve_local_env,
    wire_db_local,
    wire_db_pod,
    wire_urls,
)

_HEALTH: dict = {}


def _probe_one(name: str, port: int, svc_type: str) -> None:
    try:
        with socket.create_connection(("localhost", port), timeout=0.3):
            pass
    except OSError:
        _HEALTH[name] = "starting"
        return
    if svc_type.startswith("spring"):
        try:
            req = urllib.request.Request(f"http://localhost:{port}/actuator/health")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                body = json.loads(resp.read())
                _HEALTH[name] = "up" if body.get("status") == "UP" else "unhealthy"
        except (OSError, ValueError, json.JSONDecodeError):
            _HEALTH[name] = "up"
    else:
        _HEALTH[name] = "up"


def _health_worker(results_ref: list, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        for r in list(results_ref):
            if _pid_alive(r.get("pid")):
                _probe_one(r["name"], r["port"], r.get("type", "node"))
            else:
                _HEALTH.pop(r["name"], None)
        stop_event.wait(3.0)


def _status_str(name: str, pid: int | None) -> tuple[str, str]:
    if not _pid_alive(pid):
        return "✖ stopped", f"{RED}✖ stopped{RESET}"
    h = _HEALTH.get(name)
    if h == "up":
        return "● up", f"{GREEN}● up{RESET}"
    if h == "starting":
        return "◐ starting", f"{YELLOW}◐ starting{RESET}"
    if h == "unhealthy":
        return "✖ unhealthy", f"{RED}✖ unhealthy{RESET}"
    return "● running", f"{GREEN}● running{RESET}"


def _log_rotation_worker(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        stop_event.wait(30.0)
        if stop_event.is_set():
            break
        try:
            for log_file in constants.LOGS_DIR.glob("*.log"):
                try:
                    size = log_file.stat().st_size
                except OSError:
                    continue
                if size <= constants.LOG_MAX_BYTES:
                    continue
                try:
                    with open(log_file, "rb") as fh:
                        fh.seek(-constants.LOG_KEEP_BYTES, 2)
                        tail = fh.read()
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    header = (
                        f"# [run-local] log rotated {ts} "
                        f"({size // (1024 * 1024)} MB -> last {constants.LOG_KEEP_BYTES // (1024 * 1024)} MB)\n"
                    ).encode()
                    with open(log_file, "wb") as fh:
                        fh.write(header)
                        fh.write(tail)
                except OSError:
                    pass
        except OSError:
            pass


def _all_group_rss(pids: list) -> dict:
    if not pids:
        return {}
    totals: dict = {}
    try:
        r = subprocess.run(
            ["ps", "-A", "-o", "pid=,pgid=,rss="],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode == 0:
            pid_set = set(pids)
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    pid = int(parts[0])
                    pgid = int(parts[1])
                    rss = int(parts[2])
                    for target in (pid, pgid):
                        if target in pid_set:
                            totals[target] = totals.get(target, 0) + rss
                except ValueError:
                    pass
            if totals:
                return totals
    except (OSError, subprocess.SubprocessError):
        pass

    for pid in pids:
        try:
            os.kill(pid, 0)
            totals[pid] = totals.get(pid, 1024)
        except OSError:
            pass
    return totals


def _save_env_dump(name: str, env_vars: dict, base_env: str, db_env: str, up_mode: str) -> None:
    try:
        constants.ENVS_DIR.mkdir(parents=True, exist_ok=True)
        constants.ENVS_DIR.chmod(0o700)
        dump_file = constants.ENVS_DIR / f"{name}.env"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"# run-local.py | {name} | {ts}",
            f"# env={base_env}  db={db_env}  up={up_mode}",
            "",
        ]
        for k, v in sorted(env_vars.items()):
            lines.append(f"{k}={v}")
        dump_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        dump_file.chmod(0o600)
    except OSError:
        pass


def _port_in_use(port: int) -> str | None:
    in_use = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            in_use = False
    except OSError:
        in_use = True

    if not in_use:
        return None

    try:
        r = subprocess.run(
            ["lsof", "-nP", f"-i:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                return f"{parts[0]} (PID {parts[1]})"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown process"


def _wait_port_free(port: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_in_use(port) is None:
            return True
        time.sleep(0.3)
    return False


def _env_by_id(env_id: str) -> dict | None:
    return next((e for e in constants.ENVIRONMENTS if e["id"] == env_id), None)


_POD_ENV_CACHE: dict = {}


def fetch_env_for(cfg: dict, env_id: str) -> dict:
    if env_id == "local":
        p = resolve_local_env(cfg["path"], cfg["name"])
        return parse_set_env_sh(p) if p else {}
    key = (cfg["name"], env_id)
    if key in _POD_ENV_CACHE:
        return _POD_ENV_CACHE[key]
    ei = _env_by_id(env_id)
    d: dict = {}
    if ei and ei.get("cluster"):
        ctx = _resolve_context(ei["cluster"])
        if ctx:
            pod, _ = find_pod(cfg["name"], env_id, ctx, ei["namespace"])
            if pod:
                d = get_pod_env(pod, ctx, ei["namespace"])
    _POD_ENV_CACHE[key] = d
    return d


def _launch_one(
    cfg: dict, running_ports: dict, db_cfg: dict
) -> tuple[int | None, str | None, float | None, dict]:
    name = cfg["name"]
    env_info = cfg["env"]
    is_local = env_info["id"] == "local"
    is_fe = cfg["service"]["type"] in ("next", "vite")

    occupant = _port_in_use(cfg["port"])
    if occupant:
        return None, f"Port {cfg['port']} occupied by {occupant}", None, {}

    env_vars: dict = {}

    if is_local:
        set_env = resolve_local_env(cfg["path"], name)
        store_env = parse_set_env_sh(set_env) if set_env else {}
        if is_fe:
            for dotenv_name in (".env", ".env.local"):
                dp = cfg["path"] / dotenv_name
                if dp.exists():
                    env_vars.update(_parse_dotenv(dp))
            env_vars.update(store_env)
        else:
            env_vars = store_env
    else:
        context = _resolve_context(env_info["cluster"])
        if not context:
            return None, f"No kubectl context for cluster '{env_info['cluster']}'", None, {}
        pod, pod_err = find_pod(name, env_info["id"], context, env_info["namespace"])
        if not pod:
            if is_fe:
                for dotenv_name in (".env", f".env.{env_info['id']}", ".env.local"):
                    dp = cfg["path"] / dotenv_name
                    if dp.exists():
                        env_vars.update(_parse_dotenv(dp))
            else:
                return None, pod_err or f"Pod not found in '{env_info['id']}'", None, {}
        else:
            pod_env = get_pod_env(pod, context, env_info["namespace"])
            if not pod_env and not is_fe:
                return None, "Could not get variables from pod", None, {}
            app_vars = parse_app_vars(cfg["path"])
            clean = {k: v for k, v in pod_env.items() if not _is_noise(k)}
            env_vars = {k: v for k, v in clean.items() if k in app_vars} if app_vars else clean
            if is_fe:
                for dotenv_name in (".env", f".env.{env_info['id']}", ".env.local"):
                    dp = cfg["path"] / dotenv_name
                    if dp.exists():
                        env_vars.update(_parse_dotenv(dp))

    up_mode = cfg.get("up_mode", "auto")
    wired_map: dict = {}
    if up_mode == "auto":
        ports_for_wiring = {k: v for k, v in running_ports.items() if k != name}
        env_vars, wired_map = wire_urls(env_vars, ports_for_wiring)
    else:
        env_vars = override_urls_from_env(env_vars, fetch_env_for(cfg, up_mode))

    db_env = cfg.get("db_env", "local" if cfg.get("db_local") else env_info["id"])
    if db_env == "local":
        env_vars.update(wire_db_local(env_vars, db_cfg, cfg["path"]))
    elif db_env != env_info["id"]:
        env_vars.update(_db_vars_from(fetch_env_for(cfg, db_env)))
    elif not is_local and cfg["service"]["type"].startswith("spring"):
        env_vars.update(wire_db_pod(env_vars))

    env_vars[cfg["service"]["port_var"]] = str(cfg["port"])

    _save_env_dump(name, env_vars, env_info["id"], cfg.get("db_env", env_info["id"]), up_mode)

    cmd_list = [str(cfg["port"]) if x == "__PORT__" else x for x in cfg["service"]["cmd"]]
    if cfg["service"]["type"] == "go":
        binary = cfg["path"] / cfg["name"]
        if binary.exists():
            cmd_list = [str(binary)]

    proc_env = dict(os.environ)
    proc_env.update(env_vars)
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        proc_env["JAVA_HOME"] = java_home

    constants.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    constants.PIDS_DIR.mkdir(parents=True, exist_ok=True)

    log_path = constants.LOGS_DIR / f"{name}.log"
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(
                f"# run-local.py | {name} | env={env_info['id']} | {ts}\n"
                f"# cmd: {' '.join(cmd_list)}\n"
                f"# port: {cfg['port']}\n\n"
            )
            log_file.flush()
            proc = subprocess.Popen(
                cmd_list,
                cwd=cfg["path"],
                env=proc_env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pid_payload = {
            "pid": proc.pid,
            "name": name,
            "path": str(cfg["path"]),
            "cmd": " ".join(cmd_list),
        }
        (constants.PIDS_DIR / f"{name}.pid").write_text(json.dumps(pid_payload), encoding="utf-8")
        return proc.pid, None, time.time(), wired_map
    except OSError as exc:
        return None, str(exc), None, {}


def launch_services(configs: list, db_cfg: dict) -> tuple[list, list]:
    running_ports = {c["name"]: c["port"] for c in configs}
    results = []
    total = len(configs)

    for i, cfg in enumerate(configs, 1):
        print(
            f"  [{i}/{total}] {BOLD}{cfg['name']}{RESET}  (env={cfg['env']['id']}, port={cfg['port']})"
        )
        pid, err, started_at, wired_map = _launch_one(cfg, running_ports, db_cfg)
        if pid:
            print(f"         {GREEN}✔ PID {pid}{RESET}")
        else:
            print(f"         {RED}✖ {err}{RESET}")
        results.append(
            {
                "name": cfg["name"],
                "port": cfg["port"],
                "type": cfg["service"]["type"],
                "path": cfg["path"],
                "pid": pid,
                "error": err,
                "ok": pid is not None,
                "started_at": started_at,
            }
        )
        cfg["wiring"] = wired_map

    return results, configs


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    for target in (pid, -pid):
        try:
            os.kill(target, 0)
            return True
        except PermissionError:
            return True
        except (ProcessLookupError, OSError):
            continue
    return False


def save_state(results: list, launch_configs: list) -> None:
    by_name = {c["name"]: c for c in launch_configs}
    entries = []
    for r in results:
        cfg = by_name.get(r["name"])
        if not cfg:
            continue
        base_env = cfg.get("base_env", cfg.get("env", {}).get("id", "local"))
        entries.append(
            {
                "name": r["name"],
                "path": str(cfg["path"]),
                "port": r.get("port"),
                "type": r.get("type"),
                "env_id": base_env,
                "base_env": base_env,
                "db_env": cfg.get("db_env", "local" if cfg.get("db_local") else base_env),
                "up_mode": cfg.get("up_mode", "auto"),
                "pid": r.get("pid"),
                "started_at": r.get("started_at"),
            }
        )
    try:
        constants.DATA_DIR.mkdir(parents=True, exist_ok=True)
        constants.STATE_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_state() -> tuple[list, list]:
    if not constants.STATE_FILE.exists():
        return [], []
    try:
        entries = json.loads(constants.STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], []

    results, launch_configs = [], []
    env_by_id = {e["id"]: e for e in constants.ENVIRONMENTS}
    for e in entries:
        if not _pid_alive(e.get("pid")):
            continue
        path = Path(e["path"])
        service = detect_service(path)
        if not service:
            service = {"type": e.get("type") or "node", "cmd": [], "port_var": "PORT"}
        base_env = e.get("base_env", e.get("env_id", "local"))
        env = env_by_id.get(base_env, constants.LOCAL_ENV)
        launch_configs.append(
            {
                "name": e["name"],
                "path": path,
                "port": e.get("port"),
                "env": env,
                "base_env": base_env,
                "db_env": e.get("db_env", base_env),
                "up_mode": e.get("up_mode", "auto"),
                "service": service,
                "wiring": {},
            }
        )
        results.append(
            {
                "name": e["name"],
                "port": e.get("port"),
                "type": e.get("type") or service["type"],
                "path": path,
                "pid": e.get("pid"),
                "error": None,
                "ok": True,
                "started_at": e.get("started_at"),
            }
        )
    return results, launch_configs


def graceful_kill_pid(
    pid: int,
    timeout: float = 2.5,
    service_name: str | None = None,
    expected_cmd: str | None = None,
    service_path: Path | str | None = None,
) -> bool:
    """Tries to terminate the process with SIGTERM and escalates to SIGKILL if it persists,
    verifying identity to avoid PID reuse.

    Returns True if the process was stopped/terminated; False if it was rejected or is still alive.
    """
    if pid <= 1 or pid == os.getpid():
        return False

    # Process identity verification against PID reuse
    if service_name or expected_cmd or service_path:
        import re

        from workspace_engine.common import get_process_cmdline

        cmdline = get_process_cmdline(pid)
        if not cmdline:
            return False

        # Reject obvious false positives where service_name is just an argument to a tool
        first_token = cmdline.split()[0].lower() if cmdline.split() else ""
        disallowed_binaries = {
            "grep",
            "ripgrep",
            "rg",
            "cat",
            "vim",
            "vi",
            "nano",
            "less",
            "more",
            "ps",
            "kill",
            "pkill",
            "top",
            "htop",
            "tail",
            "head",
            "sed",
            "awk",
        }
        binary_name = Path(first_token).name
        if binary_name in disallowed_binaries:
            return False

        matched = False
        if expected_cmd and (expected_cmd in cmdline or cmdline in expected_cmd):
            matched = True
        elif service_path:
            svc_path_str = str(service_path)
            svc_path_resolved = str(Path(service_path).resolve())
            if svc_path_str in cmdline or svc_path_resolved in cmdline:
                matched = True
            else:
                # The service has a specific path (service_path).
                # If the path doesn't match cmdline, we must NEVER accept
                # the process merely because service_name matches in another
                # workspace or directory (e.g. project-a/api vs project-b/api).
                return False
        elif service_name:
            if "/" in service_name or "\\" in service_name:
                name_path = Path(service_name)
                if str(name_path) in cmdline or str(name_path.resolve()) in cmdline:
                    matched = True
                else:
                    return False
            else:
                pattern = (
                    rf"(?:/|^|\b){re.escape(service_name)}(?:/|\.py|\.ts|\.js|\.json|\.jar|:|\s|$)"
                )
                if re.search(pattern, cmdline):
                    matched = True

        if not matched:
            # PID reused by a foreign process: do not signal foreign process
            return False

    current_pgid = os.getpgrp()
    targets = [pid]
    if pid != current_pgid:
        targets.insert(0, -pid)

    # 1. Send SIGTERM
    for target in targets:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(target, 15)  # SIGTERM

    # 2. Wait for exit confirmation
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)

    # 3. Escalate to SIGKILL if still alive
    if _pid_alive(pid):
        for target in targets:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(target, 9)  # SIGKILL

    time.sleep(0.1)
    return not _pid_alive(pid)


def stop_all() -> None:
    pid_files = list(constants.PIDS_DIR.glob("*.pid"))
    if not pid_files:
        print("No active services.")
        return

    # Load recorded state if available to retrieve service path
    state_map: dict[str, str] = {}
    if constants.STATE_FILE.is_file():
        try:
            entries = json.loads(constants.STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict) and "name" in e and "path" in e:
                        state_map[e["name"]] = e["path"]
        except (OSError, json.JSONDecodeError):
            pass

    for pid_file in pid_files:
        name = pid_file.stem
        raw_text = ""
        try:
            raw_text = pid_file.read_text(encoding="utf-8").strip()
        except OSError:
            pid_file.unlink(missing_ok=True)
            continue

        pid: int | None = None
        expected_cmd: str | None = None
        file_path: str | None = None

        if raw_text.startswith("{"):
            try:
                meta = json.loads(raw_text)
                pid = int(meta.get("pid", 0))
                expected_cmd = meta.get("cmd") or meta.get("command") or meta.get("cmdline")
                file_path = meta.get("path")
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        if pid is None or pid <= 0:
            try:
                pid = int(raw_text.splitlines()[0].strip())
            except (ValueError, IndexError):
                pid_file.unlink(missing_ok=True)
                continue

        svc_path = state_map.get(name) or file_path
        stopped = graceful_kill_pid(
            pid,
            service_name=name,
            expected_cmd=expected_cmd,
            service_path=svc_path,
        )
        pid_file.unlink(missing_ok=True)
        if stopped:
            print(f"  {RED}●{RESET} {name} (PID {pid}) stopped")
        else:
            print(
                f"  {YELLOW}⚠{RESET} {name} (PID {pid}) not stopped or foreign process (PID reused)"
            )
    constants.STATE_FILE.unlink(missing_ok=True)
    print()
