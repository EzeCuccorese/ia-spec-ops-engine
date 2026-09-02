#!/usr/bin/env python3
"""
kube-env.py — TUI para gestión de pods Kubernetes en proyectos de microservicios.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTALACIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Copiá este archivo en:
  ia-toolkit/scripts/kube-env.py

Dependencias obligatorias:
  kubectl   en PATH con al menos un contexto configurado.
              El script detecta los contextos disponibles automáticamente.
              Si hay varios, muestra un picker para elegir al inicio.
              → https://kubernetes.io/docs/tasks/tools/

Dependencias opcionales (habilitan features extra):

  stern     Para ver logs de MÚLTIPLES servicios simultáneamente.
              Sin stern, múltiples logs usan tmux o caen a un servicio.
              Linux:
                VER=$(curl -s https://api.github.com/repos/stern/stern/releases/latest | grep tag_name | cut -d'"' -f4)
                mkdir -p ~/.local/bin
                curl -L -o /tmp/stern.tar.gz "https://github.com/stern/stern/releases/download/${VER}/stern_${VER#v}_linux_amd64.tar.gz"
                tar xzf /tmp/stern.tar.gz -C ~/.local/bin stern && rm /tmp/stern.tar.gz
              macOS:  brew install stern
              → https://github.com/stern/stern

  tmux      Para abrir shells o ver logs de MÚLTIPLES pods en paneles.
              Sin tmux, las operaciones multi-servicio usan solo el primero.
              Linux:  sudo apt install tmux   (Ubuntu/Debian)
                      sudo yum install tmux   (RHEL/CentOS/Amazon Linux)
              macOS:  brew install tmux
              → https://github.com/tmux/tmux
              Nota: no hace falta estar dentro de una sesión tmux existente.
                    El script crea una sesión nueva automáticamente si es necesario.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  python3 kube-env.py

Flujo de la TUI:
  1. (Si hay múltiples contextos kubectl) Elegí el contexto con ↑↓, Enter.
  2. Elegí la operación con ↑↓, Enter confirma.
  3. Elegí el ambiente (faf, granos, staging, etc.).
  4. Seleccioná uno o más proyectos (SPACE marca, Enter confirma).
     Escribir filtra la lista en tiempo real.
  5. Revisá el resumen y presioná Enter para ejecutar.
  ESC vuelve al paso anterior en cualquier momento. Ctrl+C sale.

Detección automática de proyectos (en orden de prioridad):
  1. config/.env → WORKSPACE_REPOSITORIES_DIR  (workspace del toolkit)
  2. Variable de entorno PROJECT_REPOSITORIES_DIR
  3. CWD con repos .git directos (estructura flat)
  4. CWD con dominios que contienen repos (core/, merchants/, farmers/, ...)

Operación 'env' — qué genera:
  .env        formato dotenv (IntelliJ, Docker --env-file, extensiones dotenv)
  set-env.sh  bash con 'export VAR=value'; cargar con:
                source set-env.sh && ./gradlew bootRun  (Spring Boot / Gradle)
                source set-env.sh && mvn spring-boot:run  (Maven)
                source set-env.sh && yarn start          (Node.js)
  Solo incluye las vars que el proyecto realmente usa (cross-ref con
  application.yaml para Spring Boot o process.env para Node.js).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import select as _select
import shutil
import subprocess
import sys
import termios
import tty
from datetime import datetime
from pathlib import Path

# ── ANSI colors ───────────────────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
CYAN = "\033[0;36m"
YELLOW = "\033[1;33m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ── Project Configuration ──────────────────────────────────────────────────────
_CONFIG_LOADED = False


def load_project_config() -> dict:
    global _CONFIG_LOADED
    default_config = {
        "project_name": "generic",
        "domain": "generic.com",
        "namespaces": [],
        "env_slugs": [],
        "environments": [],
        "artifact_registry_domain": "generic",
        "repositories_dir_env_var": "PROJECT_REPOSITORIES_DIR",
        "local_envs_dir_name": "local-envs",
        "workspaces_dir_name": "workspaces",
        "toolkit_dir_name": "project-toolkit",
        "url_pattern": "https?://([a-z0-9-]+)\\.(?:dev|prod)\\.generic\\.com(/[^\\s]*)?",
    }
    config_path = Path.home() / ".config" / "devscripts" / "config.json"
    if not config_path.exists() and "XDG_CONFIG_HOME" in os.environ:
        config_path = Path(os.environ["XDG_CONFIG_HOME"]) / "devscripts" / "config.json"
    if not config_path.exists():
        config_path = Path("config.json")

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                user_config = json.load(f)
                for k, v in user_config.items():
                    default_config[k] = v
                _CONFIG_LOADED = True
        except Exception:
            pass
    return default_config


PROJECT_CONFIG = load_project_config()

# ── Operations ────────────────────────────────────────────────────────────────

OPERATIONS = [
    {
        "id": "env",
        "label": "env      — Extraer variables de entorno",
        "multi": True,
        "description": [
            "Conecta al pod y extrae las variables de entorno",
            "configuradas. Las cruza con application.yaml (Spring",
            "Boot) o process.env (Node.js) para incluir solo las",
            "vars que el proyecto realmente usa.",
            "",
            "Genera en el directorio de cada proyecto:",
            "  .env        → dotenv (editores, Docker, IntelliJ)",
            "  set-env.sh  → bash con export, para correr local:",
            "    source set-env.sh && ./gradlew bootRun",
            "",
            "Soporta múltiples proyectos en simultáneo.",
        ],
    },
    {
        "id": "logs",
        "label": "logs     — Ver logs en tiempo real",
        "multi": True,
        "description": [
            "Muestra logs del pod en tiempo real.",
            "",
            "1 proyecto  → kubectl logs --tail=100 -f",
            "",
            "Múltiples proyectos:",
            "  Con stern  → logs intercalados con colores por",
            "               servicio (recomendado).",
            "  Sin stern  → tmux: un panel por servicio.",
            "  Sin ninguno → solo el primer servicio.",
            "",
            "Instalar stern (recomendado para multi-logs):",
            "  Linux/macOS: ver cabecera del script",
            "",
            "Ctrl+C para detener.",
        ],
    },
    {
        "id": "exec",
        "label": "exec     — Abrir shell en el pod",
        "multi": True,
        "description": [
            'Abre una terminal sh en el container "application".',
            "",
            "1 proyecto  → kubectl exec -it directamente.",
            "",
            "Múltiples proyectos:",
            "  Con tmux   → un panel separado por servicio.",
            "  Sin tmux   → solo el primer servicio.",
            "",
            "Instalar tmux (requerido para multi-exec):",
            "  Linux: sudo apt install tmux",
            "  macOS: brew install tmux",
            "",
            "Útil para inspeccionar filesystem, depurar",
            "conectividad o revisar config en runtime.",
        ],
    },
    {
        "id": "restart",
        "label": "restart  — Reiniciar pods",
        "multi": True,
        "description": [
            "Elimina los pods por label app=<nombre> para que",
            "Kubernetes los recree con la misma imagen.",
            "",
            "Útil para aplicar cambios de ConfigMap/Secret o",
            "recuperarse de un estado corrupto sin nuevo deploy.",
            "",
            "Soporta múltiples proyectos en simultáneo.",
        ],
    },
    {
        "id": "image",
        "label": "image    — Ver imagen desplegada",
        "multi": True,
        "description": [
            'Muestra la imagen Docker del container "application"',
            "(nombre:tag) para saber qué versión está corriendo,",
            "sin entrar al panel de Nullplatform.",
            "",
            "Soporta múltiples proyectos en simultáneo.",
        ],
    },
]

# ── Environments ──────────────────────────────────────────────────────────────

ENVIRONMENTS = PROJECT_CONFIG["environments"]

# ── Noise vars filter ─────────────────────────────────────────────────────────

_NOISE_EXACT = {
    "HOSTNAME",
    "HOME",
    "PATH",
    "USER",
    "SHELL",
    "SHLVL",
    "PWD",
    "OLDPWD",
    "LANG",
    "_",
    "TERM",
    "TERM_PROGRAM",
    "COLORTERM",
}
_NOISE_PREFIX = ("KUBERNETES_", "JAVA_", "LC_", "LS_COLORS", "JVM_")
_NOISE_SUFFIX = ("_SERVICE_HOST", "_SERVICE_PORT")


def _is_noise(key: str) -> bool:
    if key in _NOISE_EXACT:
        return True
    if any(key.startswith(p) for p in _NOISE_PREFIX):
        return True
    if any(key.endswith(s) for s in _NOISE_SUFFIX):
        return True
    return bool(re.match(r"^[A-Z0-9_]+-?\d*_PORT(_\d+_TCP.*)?$", key))


# ── Project / path detection ──────────────────────────────────────────────────


def _parse_dotenv(path: Path) -> dict:
    env: dict = {}
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def find_repos_root() -> Path | None:
    for candidate in [Path.cwd(), Path.cwd().parent]:
        env_file = candidate / "config" / ".env"
        if env_file.exists():
            cfg = _parse_dotenv(env_file)
            repos_dir = cfg.get("WORKSPACE_REPOSITORIES_DIR", "repositories")
            p = candidate / repos_dir
            if p.exists() and p.is_dir():
                return p

    env_vars_to_check = [
        PROJECT_CONFIG.get("repositories_dir_env_var"),
        "AI_REPOSITORIES_DIR",
        "PROJECT_REPOSITORIES_DIR",
    ]
    for env_var in env_vars_to_check:
        if env_var and (env_dir := os.environ.get(env_var)):
            p = Path(os.path.expanduser(env_dir))
            if p.exists():
                return p

    try:
        cwd = Path.cwd()
        # Flat structure: direct children have .git
        git_dirs = [d for d in cwd.iterdir() if d.is_dir() and (d / ".git").exists()]
        if len(git_dirs) >= 2:
            return cwd

        # Two-level structure: Root with domain subdirs (core/, merchants/, ...)
        nested: list = []
        for d in cwd.iterdir():
            if d.is_dir() and not (d / ".git").exists():
                with contextlib.suppress(PermissionError):
                    nested.extend(s for s in d.iterdir() if s.is_dir() and (s / ".git").exists())
        if len(nested) >= 2:
            return cwd
    except PermissionError:
        pass

    return None


def load_projects(root: Path) -> list:
    results: list = []
    try:
        for d in root.iterdir():
            if not d.is_dir():
                continue
            if (d / ".git").exists():
                results.append(d.name)
            else:
                # Domain subdir (core/, merchants/, farmers/, ...)
                try:
                    for sub in d.iterdir():
                        if sub.is_dir() and (sub / ".git").exists():
                            results.append(sub.name)
                except PermissionError:
                    pass
    except PermissionError:
        pass
    return sorted(results)


def get_project_path(repos_root: Path | None, project_name: str) -> Path:
    if repos_root:
        direct = repos_root / project_name
        if direct.exists():
            return direct
        # Two-level: search inside domain subdirs
        try:
            for d in repos_root.iterdir():
                if d.is_dir():
                    candidate = d / project_name
                    if candidate.exists() and (candidate / ".git").exists():
                        return candidate
        except PermissionError:
            pass
    return Path.cwd()


# ── kubectl context detection ────────────────────────────────────────────────


def get_kubectl_contexts() -> list:
    """Returns list of available kubectl context names."""
    r = subprocess.run(
        ["kubectl", "config", "get-contexts", "-o", "name"], capture_output=True, text=True
    )
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def resolve_contexts(available: list) -> dict:
    """Maps 'dev'/'prod' categories to actual context names.

    Heuristic: contexts containing 'prod' map to prod, others to dev.
    Returns {'dev': ctx_name_or_None, 'prod': ctx_name_or_None}.
    """
    mapping: dict = {"dev": None, "prod": None}
    for ctx in available:
        low = ctx.lower()
        if "prod" in low:
            mapping["prod"] = ctx
        else:
            mapping["dev"] = ctx
    return mapping


def pick_context_if_needed(tty_fd, available: list, category: str) -> str | None:
    """If multiple contexts exist for the category, let the user pick one."""
    if not available:
        return None
    if len(available) == 1:
        return available[0]
    items = [{"label": ctx, "id": ctx, "description": []} for ctx in available]
    idx = panel_picker(tty_fd, f"Contexto kubectl ({category})", items)
    if idx is None:
        return None
    return available[idx]


# ── App config parsing ────────────────────────────────────────────────────────


def parse_app_vars(project_path: Path) -> list:
    found: set = set()
    spring_re = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::[^}]*)?\}")
    node_re = re.compile(r"process\.env\.([A-Z_][A-Z0-9_]*)")

    for candidate in [
        project_path / "src" / "main" / "resources" / "application.yaml",
        project_path / "src" / "main" / "resources" / "application.yml",
        project_path / "src" / "main" / "resources" / "application.properties",
    ]:
        if candidate.exists():
            for m in spring_re.finditer(candidate.read_text(errors="ignore")):
                found.add(m.group(1))

    if (project_path / "package.json").exists():
        src_root = project_path / "src"
        if not src_root.exists():
            src_root = project_path
        for ext in ("*.js", "*.ts"):
            for src_file in src_root.rglob(ext):
                if "node_modules" in src_file.parts:
                    continue
                try:
                    for m in node_re.finditer(src_file.read_text(errors="ignore")):
                        found.add(m.group(1))
                except OSError:
                    pass

    return sorted(found)


# ── Kubernetes helpers ────────────────────────────────────────────────────────


def _kubectl(*args, context: str = "dev") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", "--context", context] + list(args),
        capture_output=True,
        text=True,
    )


def find_pod(
    service_name: str, workspace_env: str, context: str = "dev", namespace: str = "sandbox"
) -> tuple:
    """Returns (pod_name, error). pod_name is None when not found or on error."""
    r = _kubectl("get", "pods", "-n", namespace, context=context)
    if r.returncode != 0:
        msg = r.stderr.strip() or "kubectl falló sin mensaje de error"
        return None, msg
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        name, status = parts[0], parts[2]
        if service_name in name and f"-{workspace_env}-" in name:
            if status == "Running":
                return name, None
            else:
                return None, f"Pod encontrado pero no está Running (estado: {status})"
    return None, None


def get_pod_env(pod_name: str, context: str = "dev", namespace: str = "sandbox") -> dict:
    r = _kubectl(
        "exec", "-n", namespace, "-c", "application", pod_name, "--", "env", context=context
    )
    if r.returncode != 0:
        return {}
    _env_key = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    result: dict = {}
    current_key: str | None = None
    for line in r.stdout.splitlines():
        if _env_key.match(line):
            k, _, v = line.partition("=")
            result[k] = v
            current_key = k
        elif current_key is not None:
            result[current_key] += "\n" + line
    return result


def filter_env_vars(pod_env: dict, app_vars: list) -> tuple:
    clean = {k: v for k, v in pod_env.items() if not _is_noise(k)}
    if not app_vars:
        return clean, []
    filtered = {k: v for k, v in clean.items() if k in app_vars}
    missing = [v for v in app_vars if v not in pod_env]
    return filtered, missing


def write_env_files(project_path: Path, env_vars: dict, pod_name: str, workspace_env: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    hdr = f"# Generado por kube-env.py  |  pod: {pod_name}  |  env: {workspace_env}  |  {ts}"

    lines = [hdr]
    for k, v in sorted(env_vars.items()):
        if "\n" in v:
            dq_escaped = v.replace('"', '\\"')
            lines.append(f'{k}="{dq_escaped}"')
        else:
            lines.append(f"{k}={v}")
    (project_path / ".env").write_text("\n".join(lines) + "\n")

    sh = ["#!/bin/bash", hdr, "# Uso: source set-env.sh"]
    for k, v in sorted(env_vars.items()):
        escaped = v.replace("'", "'\\''")
        sh.append(f"export {k}='{escaped}'")
    dest = project_path / "set-env.sh"
    dest.write_text("\n".join(sh) + "\n")
    dest.chmod(0o755)


# ── Multi-tool detection ──────────────────────────────────────────────────────


def _has_stern() -> bool:
    return shutil.which("stern") is not None


def _has_tmux() -> bool:
    return shutil.which("tmux") is not None


def _in_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


# ── Multi-logs (stern / tmux / fallback) ──────────────────────────────────────


def _launch_logs_multi(projects: list, env: dict, tty_fd, old_attrs):
    """Exit TUI and stream logs for multiple services.

    Priority:
      1. stern  — interleaved logs with per-service colors (best UX)
      2. tmux   — one split pane per service
      3. fallback — warn and stream first service only
    """
    ns = env["namespace"]
    ctx = env["cluster"]

    # Resolve pods before leaving the TUI so we can report errors cleanly
    pod_results = [(p, *find_pod(p, env["id"], ctx, ns)) for p in projects]
    found = [(p, pod) for p, pod, _ in pod_results if pod is not None]
    missing = [(p, err) for p, pod, err in pod_results if pod is None]

    _w(tty_fd, "\033[?1049l\033[?25h")
    termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
    tty_fd.close()

    if missing:
        print()
        for p, err in missing:
            if err:
                print(f"{YELLOW}⚠  {p}: {err}{RESET}")
            else:
                print(
                    f"{YELLOW}⚠  {p}: pod no encontrado en {env['id']} "
                    f"(¿VPN conectada? ¿pod corriendo?){RESET}"
                )

    if not found:
        print(f"{RED}❌ Sin pods disponibles.{RESET}")
        sys.exit(1)

    if len(found) == 1:
        os.execvp(
            "kubectl",
            [
                "kubectl",
                "--context",
                ctx,
                "logs",
                "-n",
                ns,
                "-c",
                "application",
                "--tail=100",
                "-f",
                found[0][1],
            ],
        )
        return

    # Multiple pods — prefer stern
    if _has_stern():
        pattern = "(" + "|".join(p for p, _ in found) + f").*-{env['id']}-"
        print(f"{DIM}Usando stern para {len(found)} servicios...{RESET}")
        os.execvp(
            "stern",
            [
                "stern",
                pattern,
                "--context",
                ctx,
                "-n",
                ns,
                "-c",
                "application",
                "--tail",
                "100",
            ],
        )
        return

    # No stern — try tmux panes
    if _has_tmux():
        session = f"kube-logs-{env['id']}"
        print(f"{DIM}Abriendo {len(found)} paneles tmux (sesión: {session})...{RESET}")
        cmds = [
            f"kubectl --context {ctx} logs -n {ns} -c application --tail=100 -f {pod}"
            for _, pod in found
        ]
        if _in_tmux():
            # Already inside tmux — use split-window
            for cmd in cmds[1:]:
                subprocess.run(["tmux", "split-window", "-h", cmd])
            os.execvp("kubectl", cmds[0].split())
        else:
            # Launch new tmux session
            subprocess.run(["tmux", "new-session", "-d", "-s", session, cmds[0]])
            for cmd in cmds[1:]:
                subprocess.run(["tmux", "split-window", "-t", session, "-h", cmd])
            subprocess.run(["tmux", "select-layout", "-t", session, "tiled"])
            os.execvp("tmux", ["tmux", "attach-session", "-t", session])
        return

    # Nothing available — stream first pod only
    print(
        f"{YELLOW}⚠  stern y tmux no disponibles. Solo se mostrarán logs de: {found[0][0]}{RESET}"
    )
    print(f"{DIM}  Instalar stern:  brew install stern  |  ver cabecera del script{RESET}")
    print(f"{DIM}  Instalar tmux:   sudo apt install tmux  |  brew install tmux{RESET}\n")
    os.execvp(
        "kubectl",
        [
            "kubectl",
            "--context",
            ctx,
            "logs",
            "-n",
            ns,
            "-c",
            "application",
            "--tail=100",
            "-f",
            found[0][1],
        ],
    )


# ── Multi-exec (tmux / fallback) ──────────────────────────────────────────────


def _launch_exec_multi(projects: list, env: dict, tty_fd, old_attrs):
    """Exit TUI and open shells for multiple services.

    Priority:
      1. tmux   — one split pane per service
      2. fallback — warn and exec into first service only
    """
    ns = env["namespace"]
    ctx = env["cluster"]

    pod_results = [(p, *find_pod(p, env["id"], ctx, ns)) for p in projects]
    found = [(p, pod) for p, pod, _ in pod_results if pod is not None]
    missing = [(p, err) for p, pod, err in pod_results if pod is None]

    _w(tty_fd, "\033[?1049l\033[?25h")
    termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
    tty_fd.close()

    if missing:
        print()
        for p, err in missing:
            if err:
                print(f"{YELLOW}⚠  {p}: {err}{RESET}")
            else:
                print(
                    f"{YELLOW}⚠  {p}: pod no encontrado en {env['id']} "
                    f"(¿VPN conectada? ¿pod corriendo?){RESET}"
                )

    if not found:
        print(f"{RED}❌ Sin pods disponibles.{RESET}")
        sys.exit(1)

    if len(found) == 1:
        os.execvp(
            "kubectl",
            [
                "kubectl",
                "--context",
                ctx,
                "exec",
                "-it",
                "-n",
                ns,
                "-c",
                "application",
                found[0][1],
                "--",
                "sh",
            ],
        )
        return

    if _has_tmux():
        session = f"kube-exec-{env['id']}"
        print(f"{DIM}Abriendo {len(found)} paneles tmux (sesión: {session})...{RESET}")
        cmds = [
            f"kubectl --context {ctx} exec -it -n {ns} -c application {pod} -- sh"
            for _, pod in found
        ]
        if _in_tmux():
            for cmd in cmds[1:]:
                subprocess.run(["tmux", "split-window", "-h", cmd])
            os.execvp("kubectl", cmds[0].split())
        else:
            subprocess.run(["tmux", "new-session", "-d", "-s", session, cmds[0]])
            for cmd in cmds[1:]:
                subprocess.run(["tmux", "split-window", "-t", session, "-h", cmd])
            subprocess.run(["tmux", "select-layout", "-t", session, "tiled"])
            os.execvp("tmux", ["tmux", "attach-session", "-t", session])
        return

    print(f"{YELLOW}⚠  tmux no disponible. Solo se abrirá shell en: {found[0][0]}{RESET}")
    print(f"{DIM}  Instalar tmux: sudo apt install tmux  |  brew install tmux{RESET}\n")
    os.execvp(
        "kubectl",
        [
            "kubectl",
            "--context",
            ctx,
            "exec",
            "-it",
            "-n",
            ns,
            "-c",
            "application",
            found[0][1],
            "--",
            "sh",
        ],
    )


# ── TUI primitives ────────────────────────────────────────────────────────────


def _open_tty():
    return open("/dev/tty", "rb+", buffering=0)


def _read_key(tty_fd) -> bytes:
    ch = tty_fd.read(1)
    if ch == b"\x1b":
        r, _, _ = _select.select([tty_fd], [], [], 0.1)
        if r:
            return b"\x1b" + tty_fd.read(2)
    return ch


def _w(tty_fd, s: str):
    tty_fd.write(s.encode())


def _sep(cols: int, char: str = "═", bold: bool = True) -> str:
    color = (BOLD + CYAN) if bold else DIM
    return color + char * (cols - 2) + RESET


# ── Panel: single-select with live description ────────────────────────────────


def panel_picker(tty_fd, title: str, items: list, hint: str = "") -> int | None:
    cursor = 0
    while True:
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(60, cols)
        desc = items[cursor].get("description", [])

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  {title}{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        out.append(f"  {DIM}↑↓ navegar   Enter confirmar   ESC volver{RESET}\r\n")
        if hint:
            out.append(f"  {DIM}{hint}{RESET}\r\n")
        out.append("\r\n")

        for i, item in enumerate(items):
            if i == cursor:
                out.append(f"  {BOLD}{CYAN}▶ {item['label']}{RESET}\r\n")
            else:
                out.append(f"    {DIM}{item['label']}{RESET}\r\n")

        if desc:
            out.append("\r\n")
            out.append(_sep(cols, "─", bold=False) + "\r\n")
            for line in desc:
                out.append(f"  {DIM}{line}{RESET}\r\n" if line else "\r\n")
            out.append(_sep(cols, "─", bold=False) + "\r\n")

        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return None
        elif key == b"\x03":
            sys.exit(130)
        elif key == b"\x1b[A":
            cursor = max(0, cursor - 1)
        elif key == b"\x1b[B":
            cursor = min(len(items) - 1, cursor + 1)
        elif key in (b"\r", b"\n", b""):
            return cursor


# ── Panel: project multi-select ───────────────────────────────────────────────


def panel_projects(tty_fd, projects: list, ctx_label: str, allow_multi: bool) -> list | None:
    cursor = 0
    scroll = 0
    fstr = ""
    selected: list = []
    error = ""

    def _filtered() -> list:
        if not fstr:
            return list(projects)
        q = fstr.lower()
        return [p for p in projects if q in p.lower()]

    while True:
        filtered = _filtered()
        total = len(filtered)
        cursor = min(cursor, max(0, total - 1))

        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(60, cols)
        lh = max(4, rows - 13)
        if cursor < scroll:
            scroll = cursor
        elif cursor >= scroll + lh:
            scroll = cursor - lh + 1

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  Proyectos  {DIM}[{ctx_label}]{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        if allow_multi:
            out.append(
                f"  {DIM}↑↓ navegar   SPACE seleccionar   Enter confirmar   ESC volver{RESET}\r\n"
            )
        else:
            out.append(f"  {DIM}↑↓ navegar   Enter seleccionar   ESC volver{RESET}\r\n")
        out.append("\r\n")

        if fstr:
            out.append(f"  {BOLD}Filtro:{RESET} {YELLOW}{fstr}{RESET}\r\n")
        else:
            out.append(f"  {DIM}Filtro: escribí para buscar...{RESET}\r\n")
        out.append("\r\n")
        out.append(_sep(cols, "─", bold=False) + "\r\n")

        if not filtered:
            out.append(f"  {RED}Sin resultados para '{fstr}'.{RESET}\r\n")
        else:
            window = filtered[scroll : scroll + lh]
            for j, item in enumerate(window):
                abs_i = scroll + j
                is_cur = abs_i == cursor
                in_sel = item in selected
                hint = (
                    " ↑"
                    if j == 0 and scroll > 0
                    else " ↓"
                    if j == len(window) - 1 and scroll + lh < total
                    else "  "
                )
                if allow_multi:
                    chk = "[✔]" if in_sel else "[ ]"
                    color = GREEN if in_sel else (CYAN if is_cur else DIM)
                    mark = "▶" if is_cur else " "
                    out.append(f"  {color}{mark} {chk} {item}{RESET}{hint}\r\n")
                else:
                    mark = f"{BOLD}{CYAN}▶{RESET}" if is_cur else " "
                    out.append(f"  {mark} {item}{hint}\r\n")

        out.append(_sep(cols, "─", bold=False) + "\r\n")
        out.append("\r\n")

        if allow_multi:
            if selected:
                out.append(
                    f"  {BOLD}Seleccionados ({len(selected)}):{RESET} "
                    f"{GREEN}{', '.join(selected)}{RESET}\r\n"
                )
            else:
                out.append(f"  {DIM}Ningún proyecto seleccionado aún.{RESET}\r\n")

        if error:
            out.append(f"\r\n  {RED}{error}{RESET}\r\n")
            error = ""

        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return None
        elif key == b"\x03":
            sys.exit(130)
        elif key == b"\x1b[A":
            cursor = max(0, cursor - 1)
        elif key == b"\x1b[B":
            cursor = min(max(0, total - 1), cursor + 1)
        elif key in (b"\r", b"\n", b""):
            if allow_multi:
                if selected:
                    return selected
                error = "❌ Seleccioná al menos un proyecto."
            else:
                if filtered:
                    return [filtered[cursor]]
                error = "❌ No hay proyectos disponibles."
        elif key == b" " and allow_multi:
            if filtered:
                item = filtered[cursor]
                if item in selected:
                    selected.remove(item)
                else:
                    selected.append(item)
        elif key in (b"\x7f", b"\x08"):
            if fstr:
                fstr = fstr[:-1]
                cursor = 0
                scroll = 0
        else:
            ch = key.decode("utf-8", errors="ignore")
            if ch.isprintable():
                fstr += ch
                cursor = 0
                scroll = 0


# ── Panel: confirm ────────────────────────────────────────────────────────────


def panel_confirm(tty_fd, op: dict, env: dict, projects: list, repos_root: Path | None) -> bool:
    while True:
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(60, cols)

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  Confirmar{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        out.append(f"  {DIM}Enter ejecutar   ESC volver{RESET}\r\n")
        out.append("\r\n")
        out.append(f"  {BOLD}Operación:{RESET}  {op['label']}\r\n")
        out.append(f"  {BOLD}Ambiente:{RESET}   {env['label']}\r\n")
        out.append(f"  {BOLD}Proyectos:{RESET}  {projects[0]}\r\n")
        for p in projects[1:]:
            out.append(f"              {p}\r\n")
        if repos_root:
            out.append("\r\n")
            out.append(f"  {DIM}Directorio: {repos_root}{RESET}\r\n")

        # Note for multi logs/exec about required tools
        if len(projects) > 1 and op["id"] == "logs":
            out.append("\r\n")
            if _has_stern():
                out.append(
                    f"  {GREEN}✔{RESET}  {DIM}stern detectado → logs intercalados{RESET}\r\n"
                )
            elif _has_tmux():
                suffix = "en sesión tmux existente" if _in_tmux() else "en nueva sesión tmux"
                out.append(
                    f"  {YELLOW}·{RESET}  {DIM}stern no encontrado → se usará tmux ({suffix}){RESET}\r\n"
                )
            else:
                out.append(
                    f"  {YELLOW}⚠{RESET}  {DIM}stern y tmux no encontrados → "
                    f"solo {projects[0]}{RESET}\r\n"
                )
        elif len(projects) > 1 and op["id"] == "exec":
            out.append("\r\n")
            if _has_tmux():
                suffix = "en sesión tmux existente" if _in_tmux() else "en nueva sesión tmux"
                out.append(
                    f"  {GREEN}✔{RESET}  {DIM}tmux detectado → un panel por servicio ({suffix}){RESET}\r\n"
                )
            else:
                out.append(
                    f"  {YELLOW}⚠{RESET}  {DIM}tmux no encontrado → solo {projects[0]}{RESET}\r\n"
                )

        out.append("\r\n")
        out.append(f"{BOLD}{GREEN}▶ [ Ejecutar ]{RESET}\r\n")

        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)
        if key == b"\x1b":
            return False
        elif key == b"\x03":
            sys.exit(130)
        elif key in (b"\r", b"\n", b""):
            return True


# ── Execution: env / image / restart ─────────────────────────────────────────


def _exec_env(projects: list, env: dict, repos_root: Path | None) -> list:
    results = []
    for project in projects:
        r: dict = {
            "project": project,
            "ok": False,
            "pod": None,
            "vars_total": 0,
            "vars_used": 0,
            "missing": [],
            "error": None,
        }
        pod, kubectl_err = find_pod(project, env["id"], env["cluster"], env["namespace"])
        if not pod:
            r["error"] = kubectl_err or f"Pod no encontrado para '{project}' en '{env['id']}'"
            results.append(r)
            continue

        r["pod"] = pod
        pod_env = get_pod_env(pod, env["cluster"], env["namespace"])
        if not pod_env:
            r["error"] = "No se pudieron obtener las variables del pod"
            results.append(r)
            continue

        r["vars_total"] = len(pod_env)
        project_path = get_project_path(repos_root, project)
        app_vars = parse_app_vars(project_path)
        filtered, missing = filter_env_vars(pod_env, app_vars)
        r["vars_used"] = len(filtered)
        r["missing"] = missing
        write_env_files(project_path, filtered, pod, env["id"])
        r["ok"] = True
        results.append(r)
    return results


def _exec_image(projects: list, env: dict) -> list:
    results = []
    for project in projects:
        pod, kubectl_err = find_pod(project, env["id"], env["cluster"], env["namespace"])
        if not pod:
            results.append(
                {"project": project, "ok": False, "error": kubectl_err or "Pod no encontrado"}
            )
            continue
        r = _kubectl(
            "get",
            "pod",
            pod,
            "-n",
            env["namespace"],
            "-o",
            "jsonpath={.spec.containers[?(@.name=='application')].image}",
            context=env["cluster"],
        )
        image = r.stdout.strip() if r.returncode == 0 else "(error)"
        results.append({"project": project, "ok": r.returncode == 0, "pod": pod, "image": image})
    return results


def _exec_restart(projects: list, env: dict) -> list:
    results = []
    for project in projects:
        pod, kubectl_err = find_pod(project, env["id"], env["cluster"], env["namespace"])
        if not pod:
            results.append(
                {"project": project, "ok": False, "error": kubectl_err or "Pod no encontrado"}
            )
            continue
        r = _kubectl(
            "delete", "pod", "-n", env["namespace"], "-l", f"app={project}", context=env["cluster"]
        )
        results.append(
            {
                "project": project,
                "ok": r.returncode == 0,
                "pod": pod,
                "error": r.stderr.strip() if r.returncode != 0 else None,
            }
        )
    return results


# ── Panel: results ────────────────────────────────────────────────────────────


def panel_results(tty_fd, op_id: str, results: list, repos_root: Path | None):
    while True:
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(60, cols)

        out = ["\033[H\033[J"]
        out.append(_sep(cols) + "\r\n")
        out.append(f"{BOLD}  Resultado{RESET}\r\n")
        out.append(_sep(cols) + "\r\n")
        out.append(f"  {DIM}Enter cerrar{RESET}\r\n")
        out.append("\r\n")

        ok_projects = []
        for r in results:
            proj = r["project"]
            if r.get("ok"):
                ok_projects.append(proj)
                out.append(f"  {BOLD}{proj}{RESET}\r\n")
                if r.get("pod"):
                    ps = r["pod"]
                    if len(ps) > cols - 14:
                        ps = ps[: cols - 17] + "…"
                    out.append(f"  {GREEN}✅{RESET}  pod:    {DIM}{ps}{RESET}\r\n")

                if op_id == "env":
                    out.append(
                        f"  {GREEN}✅{RESET}  vars:   "
                        f"{r['vars_total']} en pod → {r['vars_used']} relevantes\r\n"
                    )
                    base = get_project_path(repos_root, proj)
                    out.append(f"  {GREEN}✅{RESET}  .env    → {DIM}{base}/.env{RESET}\r\n")
                    out.append(f"  {GREEN}✅{RESET}  set-env → {DIM}{base}/set-env.sh{RESET}\r\n")
                    if r["missing"]:
                        ms = ", ".join(r["missing"][:4])
                        if len(r["missing"]) > 4:
                            ms += f" (+{len(r['missing']) - 4} más)"
                        out.append(
                            f"  {YELLOW}⚠️ {RESET}  sin valor en pod: {YELLOW}{ms}{RESET}\r\n"
                        )
                        out.append(
                            f"  {DIM}     → usarán el default de application.yaml{RESET}\r\n"
                        )

                elif op_id == "image":
                    out.append(f"  {GREEN}✅{RESET}  imagen: {r.get('image', '')}\r\n")

                elif op_id == "restart":
                    out.append(f"  {GREEN}✅{RESET}  pods eliminados, Kubernetes los recreará.\r\n")
            else:
                out.append(f"  {BOLD}{proj}{RESET}\r\n")
                out.append(f"  {RED}❌{RESET}  {r.get('error', 'Error desconocido')}\r\n")
            out.append("\r\n")

        if op_id == "env" and ok_projects:
            base = get_project_path(repos_root, ok_projects[0])
            out.append(_sep(cols, "─", bold=False) + "\r\n")
            out.append(f"  {DIM}Para correr localmente:{RESET}\r\n")
            out.append(f"  {CYAN}cd {base}{RESET}\r\n")
            out.append(f"  {CYAN}source set-env.sh && ./gradlew bootRun{RESET}\r\n")
            out.append(_sep(cols, "─", bold=False) + "\r\n")

        _w(tty_fd, "".join(out))

        key = _read_key(tty_fd)
        if key in (b"\r", b"\n", b"", b"\x1b"):
            return
        elif key == b"\x03":
            sys.exit(130)


# ── Main flow ─────────────────────────────────────────────────────────────────


def main():
    if not _CONFIG_LOADED and "pytest" not in sys.modules:
        print(
            f"{RED}Error: No se encontró la configuración en ~/.config/devscripts/config.json ni config.json en el directorio actual.{RESET}"
        )
        print(
            f"Por favor, copia config.json.template a ~/.config/devscripts/config.json y edita sus valores.{RESET}"
        )
        sys.exit(1)

    repos_root = find_repos_root()

    # Resolve kubectl contexts before entering TUI
    available_contexts = get_kubectl_contexts()
    ctx_map = resolve_contexts(available_contexts)

    # Build effective environments: replace category ('dev'/'prod') with real context name.
    # Environments whose category has no matching context are hidden.
    effective_envs = []
    for env_def in ENVIRONMENTS:
        category = env_def["cluster"]  # 'dev' or 'prod'
        ctx_name = ctx_map.get(category)
        if ctx_name:
            effective_envs.append({**env_def, "cluster": ctx_name})
        elif not available_contexts:
            # kubectl not working at all — keep env but error will surface later
            effective_envs.append(env_def)

    if not effective_envs:
        effective_envs = list(ENVIRONMENTS)  # fallback: show all, errors surface later

    # If multiple dev or prod contexts exist, let user pick per session
    ctx_dev_candidates = [c for c in available_contexts if "prod" not in c.lower()]
    ctx_prod_candidates = [c for c in available_contexts if "prod" in c.lower()]

    tty_fd = _open_tty()
    old_attrs = termios.tcgetattr(tty_fd)

    try:
        tty.setraw(tty_fd.fileno())
        _w(tty_fd, "\033[?25l\033[?1049h")

        # If ambiguous, pick context upfront (multiple dev or prod contexts)
        if len(ctx_dev_candidates) > 1:
            chosen = pick_context_if_needed(tty_fd, ctx_dev_candidates, "dev")
            if chosen is None:
                return
            for e in effective_envs:
                if e["cluster"] in ctx_dev_candidates:
                    e["cluster"] = chosen
        if len(ctx_prod_candidates) > 1:
            chosen = pick_context_if_needed(tty_fd, ctx_prod_candidates, "prod")
            if chosen is None:
                return
            for e in effective_envs:
                if e["cluster"] in ctx_prod_candidates:
                    e["cluster"] = chosen

        step = "op"
        op: dict | None = None
        env: dict | None = None
        selected: list = []

        while True:
            if step == "op":
                idx = panel_picker(tty_fd, "Operación", OPERATIONS)
                if idx is None:
                    break
                op = OPERATIONS[idx]
                step = "env"

            elif step == "env":
                idx = panel_picker(
                    tty_fd, "Ambiente", effective_envs, hint=f"operación: {op['id']}"
                )
                if idx is None:
                    step = "op"
                else:
                    env = effective_envs[idx]
                    step = "projects"

            elif step == "projects":
                projects_list = load_projects(repos_root) if repos_root else [Path.cwd().name]
                ctx_label = f"{op['id']} / {env['id']}"
                sel = panel_projects(tty_fd, projects_list, ctx_label, op["multi"])
                if sel is None:
                    step = "env"
                else:
                    selected = sel
                    step = "confirm"

            elif step == "confirm":
                if not panel_confirm(tty_fd, op, env, selected, repos_root):
                    step = "projects"
                else:
                    step = "execute"

            elif step == "execute":
                op_id = op["id"]

                if op_id == "logs":
                    _launch_logs_multi(selected, env, tty_fd, old_attrs)
                    return  # process replaced by execvp

                elif op_id == "exec":
                    _launch_exec_multi(selected, env, tty_fd, old_attrs)
                    return  # process replaced by execvp

                elif op_id == "env":
                    results = _exec_env(selected, env, repos_root)
                elif op_id == "image":
                    results = _exec_image(selected, env)
                elif op_id == "restart":
                    results = _exec_restart(selected, env)
                else:
                    results = [
                        {"project": p, "ok": False, "error": "Operación no implementada"}
                        for p in selected
                    ]

                panel_results(tty_fd, op_id, results, repos_root)
                step = "op"

    finally:
        try:
            _w(tty_fd, "\033[?1049l\033[?25h")
            termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
            tty_fd.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
