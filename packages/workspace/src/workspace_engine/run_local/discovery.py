"""
workspace_engine.run_local.discovery — Descubrimiento de servicios, resolución de entorno y helpers de kubectl.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from workspace_engine.run_local.service_wiring import (
    assign_port,
    service_name_from_subdomain,
    service_name_from_subdomain as _service_name_from_subdomain,
    spring_context_path,
    spring_context_path as _spring_context_path,
    node_health_path,
    node_health_path as _node_health_path,
    service_link,
    wire_urls,
    wire_db_urls,
)
from workspace_engine.run_local import constants
from workspace_engine.utils import parse_dotenv, parse_dotenv as _parse_dotenv



def _is_noise(key: str) -> bool:
    if key in constants._NOISE_EXACT:
        return True
    if any(key.startswith(p) for p in constants._NOISE_PREFIX):
        return True
    if any(key.endswith(s) for s in constants._NOISE_SUFFIX):
        return True
    if re.match(r'^[A-Z0-9_]+-?\d*_PORT(_\d+_TCP.*)?$', key):
        return True
    return False


def _ensure_config() -> dict:
    constants.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    constants.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    constants.PIDS_DIR.mkdir(parents=True, exist_ok=True)

    if not constants.DB_CFG_FILE.exists():
        constants.DB_CFG_FILE.write_text(constants._DEFAULT_DB_CFG)

    cfg = {'mongodb': 'mongodb://localhost:27018', 'postgresql': 'postgresql://localhost:5432'}
    try:
        text = constants.DB_CFG_FILE.read_text()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('mongodb:'):
                v = line.split(':', 1)[1].strip().strip('"').strip("'")
                if v:
                    cfg['mongodb'] = v
            elif line.startswith('postgresql:'):
                v = line.split(':', 1)[1].strip().strip('"').strip("'")
                if v:
                    cfg['postgresql'] = v
    except Exception:
        pass
    return cfg


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f'{s}s'
    m = s // 60
    if m < 60:
        return f'{m}m'
    h = m // 60
    m = m % 60
    if h < 24:
        return f'{h}h{m}m'
    d = h // 24
    h = h % 24
    return f'{d}d{h}h'


def _fmt_bytes(kb: int) -> str:
    if kb < 1024:
        return f'{kb}K'
    mb = kb / 1024
    if mb < 1024:
        return f'{mb:.1f}M'
    gb = mb / 1024
    return f'{gb:.1f}G'


def _service_link(svc_type: str, port: int) -> str:
    if svc_type in ('spring-gradle', 'spring-maven'):
        return f'http://localhost:{port}/swagger-ui/index.html'
    return f'http://localhost:{port}/'




_EXPORT_RE = re.compile(r"^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$")



def parse_set_env_sh(path: Path) -> dict:
    """Parse export VAR='val' lines from set-env-local.sh."""
    env: dict = {}
    try:
        for line in path.read_text(errors='ignore').splitlines():
            m = _EXPORT_RE.match(line)
            if not m:
                continue
            key = m.group(1)
            val = m.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            env[key] = val
    except OSError:
        pass
    return env


def find_envs_root(start: Path) -> Path:
    cur = start.resolve()
    local_envs_dir = constants.PROJECT_CONFIG["local_envs_dir_name"]
    workspaces_dir = constants.PROJECT_CONFIG["workspaces_dir_name"]
    toolkit_dir = constants.PROJECT_CONFIG["toolkit_dir_name"]
    for p in [cur, *cur.parents]:
        if (p / local_envs_dir).is_dir() or (p / workspaces_dir).is_dir() or (p / toolkit_dir).is_dir():
            return p
    return cur


def global_env_path(repo_path: Path, repo_name: str) -> Path:
    local_envs_dir = constants.PROJECT_CONFIG["local_envs_dir_name"]
    return find_envs_root(repo_path.parent) / local_envs_dir / f'{repo_name}.sh'


def workspace_env_path(repo_path: Path, repo_name: str) -> Optional[Path]:
    root   = find_envs_root(repo_path.parent)
    ws_dir = repo_path.parent.parent
    if ws_dir == root or not ws_dir.name:
        return None
    local_envs_dir = constants.PROJECT_CONFIG["local_envs_dir_name"]
    return root / local_envs_dir / ws_dir.name / f'{repo_name}.sh'


def resolve_local_env(repo_path: Path, repo_name: str) -> Optional[Path]:
    candidates = []
    wp = workspace_env_path(repo_path, repo_name)
    if wp:
        candidates.append(wp)
    candidates.append(repo_path / 'set-env-local.sh')
    candidates.append(global_env_path(repo_path, repo_name))
    for c in candidates:
        if c and c.exists():
            return c
    return None


def parse_app_vars(project_path: Path) -> list:
    found: set = set()
    spring_re = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(?::[^}]*)?\}')
    node_re   = re.compile(r'process\.env\.([A-Z_][A-Z0-9_]*)')

    for candidate in [
        project_path / 'src' / 'main' / 'resources' / 'application.yaml',
        project_path / 'src' / 'main' / 'resources' / 'application.yml',
        project_path / 'src' / 'main' / 'resources' / 'application.properties',
    ]:
        if candidate.exists():
            for m in spring_re.finditer(candidate.read_text(errors='ignore')):
                found.add(m.group(1))

    if (project_path / 'package.json').exists():
        src_root = project_path / 'src' if (project_path / 'src').exists() else project_path
        for ext in ('*.js', '*.ts'):
            for src_file in src_root.rglob(ext):
                if 'node_modules' in src_file.parts:
                    continue
                try:
                    for m in node_re.finditer(src_file.read_text(errors='ignore')):
                        found.add(m.group(1))
                except OSError:
                    pass

    return sorted(found)


_KUBECTL_AVAILABLE: Optional[bool] = None


def _kubectl(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(['kubectl'] + args, capture_output=True, text=True)


def _kubectl_available() -> bool:
    global _KUBECTL_AVAILABLE
    if _KUBECTL_AVAILABLE is None:
        _KUBECTL_AVAILABLE = shutil.which('kubectl') is not None
    return _KUBECTL_AVAILABLE


_kubectl_contexts_cache: Optional[list] = None


def _get_kubectl_contexts() -> list:
    global _kubectl_contexts_cache
    if _kubectl_contexts_cache is None:
        if not _kubectl_available():
            _kubectl_contexts_cache = []
        else:
            r = _kubectl(['config', 'get-contexts', '-o', 'name'])
            _kubectl_contexts_cache = (
                [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
                if r.returncode == 0 else []
            )
    return _kubectl_contexts_cache


def _resolve_context(cluster_category: str) -> Optional[str]:
    for ctx in _get_kubectl_contexts():
        if cluster_category == 'prod' and 'prod' in ctx.lower():
            return ctx
        if cluster_category == 'dev' and 'prod' not in ctx.lower():
            return ctx
    return None


def find_pod(service_name: str, app_env: str, context: str, namespace: str) -> Tuple[Optional[str], Optional[str]]:
    r = _kubectl(['--context', context, 'get', 'pods', '-n', namespace])
    if r.returncode != 0:
        return None, r.stderr.strip() or 'kubectl falló'
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        name, status = parts[0], parts[2]
        if service_name in name and f'-{app_env}-' in name:
            if status == 'Running':
                return name, None
            return None, f'Pod encontrado pero no Running ({status})'
    return None, None


def get_pod_env(pod_name: str, context: str, namespace: str) -> dict:
    r = _kubectl(['--context', context, 'exec', '-n', namespace, '-c', 'application', pod_name, '--', 'env'])
    if r.returncode != 0:
        return {}
    _env_key = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
    result: dict = {}
    current_key: Optional[str] = None
    for line in r.stdout.splitlines():
        if _env_key.match(line):
            k, _, v = line.partition('=')
            result[k] = v
            current_key = k
        elif current_key is not None:
            result[current_key] += '\n' + line
    return result


_MONGO_URI_RE = re.compile(r'^mongodb(\+srv)?://', re.IGNORECASE)
_PG_URI_RE    = re.compile(r'^(jdbc:)?postgres(ql)?://', re.IGNORECASE)


def override_urls_from_env(env_vars: dict, src_env: dict) -> dict:
    out = dict(env_vars)
    domain = constants.PROJECT_CONFIG["domain"]
    for k, v in env_vars.items():
        if domain in str(v) and k in src_env:
            out[k] = src_env[k]
    return out


def wire_db_pod(env_vars: dict) -> dict:
    result: dict = {}
    if 'SPRING_DATA_MONGODB_URI' not in env_vars:
        mongo = sorted({v.strip() for v in env_vars.values() if _MONGO_URI_RE.match(v.strip())})
        if len(mongo) == 1:
            result['SPRING_DATA_MONGODB_URI'] = mongo[0]
    if 'SPRING_DATASOURCE_URL' not in env_vars:
        pg = sorted({v.strip() for v in env_vars.values() if _PG_URI_RE.match(v.strip())})
        if len(pg) == 1:
            url = pg[0]
            if not url.lower().startswith('jdbc:'):
                if url.lower().startswith('postgres://'):
                    url = 'postgresql://' + url[len('postgres://'):]
                url = 'jdbc:' + url
            result['SPRING_DATASOURCE_URL'] = url
    return result


def _db_vars_from(src_env: dict) -> dict:
    out: dict = {}
    for k, v in src_env.items():
        sv = str(v).strip()
        if k.startswith(('MONGO', 'SPRING_DATA_MONGODB', 'SPRING_DATASOURCE')) \
           or _MONGO_URI_RE.match(sv) or _PG_URI_RE.match(sv):
            out[k] = v
    out.update(wire_db_pod(src_env))
    return out


def wire_db_local(env_vars: dict, db_cfg: dict, repo_path: Path) -> dict:
    result: dict = {}
    is_spring = any((repo_path / f).exists() for f in ('gradlew', 'mvnw', 'build.gradle', 'pom.xml'))

    has_mongo = any(_MONGO_URI_RE.match(v.strip()) for v in env_vars.values())
    has_pg    = any(_PG_URI_RE.match(v.strip()) for v in env_vars.values())

    if not has_mongo and not has_pg and is_spring:
        for build_file in ['build.gradle', 'build.gradle.kts', 'pom.xml']:
            bf = repo_path / build_file
            if bf.exists():
                content = bf.read_text(errors='ignore').lower()
                if 'mongodb' in content:
                    has_mongo = True
                if 'postgresql' in content or 'postgres' in content:
                    has_pg = True
                break

    if has_mongo:
        existing = next((v.strip() for v in env_vars.values() if _MONGO_URI_RE.match(v.strip())), None)
        if existing:
            db_part = re.sub(r'^mongodb(\+srv)?://[^/]+', db_cfg['mongodb'], existing)
        else:
            db_part = db_cfg['mongodb']
        result['SPRING_DATA_MONGODB_URI'] = db_part

    if has_pg:
        existing = next((v.strip() for v in env_vars.values() if _PG_URI_RE.match(v.strip())), None)
        if existing:
            db_part = re.sub(r'^(jdbc:)?postgres(ql)?://[^/]+', db_cfg['postgresql'], existing)
            if not db_part.lower().startswith('jdbc:'):
                db_part = 'jdbc:' + db_part
        else:
            db_part = 'jdbc:' + db_cfg['postgresql']
        result['SPRING_DATASOURCE_URL'] = db_part

    return result


def _has_spring_boot_app(repo_path: Path) -> bool:
    main_dir = repo_path / 'src' / 'main' / 'java'
    if not main_dir.exists():
        return False
    for java_file in main_dir.rglob('*Application.java'):
        try:
            if '@SpringBootApplication' in java_file.read_text(errors='ignore'):
                return True
        except OSError:
            pass
    return False


def _read_pkg(repo_path: Path) -> Optional[dict]:
    pkg = repo_path / 'package.json'
    if not pkg.exists():
        return None
    try:
        return json.loads(pkg.read_text())
    except Exception:
        return None


def _is_fe_framework(repo_path: Path) -> Optional[str]:
    data = _read_pkg(repo_path)
    if not data:
        return None
    deps    = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
    scripts = data.get('scripts', {})
    if 'next' in deps or any('next' in s for s in scripts.values()):
        return 'next'
    if 'vite' in deps or any(re.search(r'\bvite\b', s) for s in scripts.values()):
        return 'vite'
    return None


def _is_go_service(repo_path: Path) -> bool:
    if not (repo_path / 'go.mod').exists():
        return False
    if (repo_path / 'main.go').exists():
        return True
    for d in ('cmd', 'cli'):
        base = repo_path / d
        if base.is_dir() and any(base.rglob('main.go')):
            return True
    return False


def _go_run_cmd(repo_path: Path) -> list:
    for sub in ('cli/http', 'cmd/http', 'cmd/server', 'cmd/api', 'cmd'):
        if (repo_path / sub / 'main.go').exists():
            return ['go', 'run', f'./{sub}']
    if (repo_path / 'main.go').exists():
        return ['go', 'run', '.']
    for d in ('cli', 'cmd'):
        base = repo_path / d
        if base.is_dir():
            for m in sorted(base.rglob('main.go')):
                rel = m.parent.relative_to(repo_path)
                return ['go', 'run', f'./{rel}']
    return ['go', 'run', '.']


def _node_start_cmd(repo_path: Path) -> Optional[list]:
    data = _read_pkg(repo_path)
    if not data:
        return None
    scripts = data.get('scripts', {})
    if 'dev' in scripts:
        return ['npm', 'run', 'dev']
    if 'start' in scripts:
        return ['npm', 'start']
    return None


def detect_service(repo_path: Path) -> Optional[dict]:
    if _has_spring_boot_app(repo_path):
        if (repo_path / 'gradlew').exists() or (repo_path / 'build.gradle').exists() or (repo_path / 'build.gradle.kts').exists():
            return {'type': 'spring-gradle', 'cmd': ['./gradlew', 'bootRun'], 'port_var': 'SERVER_PORT'}
        if (repo_path / 'mvnw').exists() or (repo_path / 'pom.xml').exists():
            return {'type': 'spring-maven', 'cmd': ['./mvnw', 'spring-boot:run'], 'port_var': 'SERVER_PORT'}

    fe = _is_fe_framework(repo_path)
    if fe:
        return {'type': fe, 'cmd': ['npm', 'run', 'dev', '--', '--port', '__PORT__'], 'port_var': 'PORT'}

    cmd = _node_start_cmd(repo_path)
    if cmd:
        return {'type': 'node', 'cmd': cmd, 'port_var': 'PORT'}

    if _is_go_service(repo_path):
        return {'type': 'go', 'cmd': _go_run_cmd(repo_path), 'port_var': 'PORT'}

    return None


def find_project_root(start: Path) -> Optional[Path]:
    """Scans parent directories for repository boundaries."""
    candidate = start
    workspaces_dir = constants.PROJECT_CONFIG["workspaces_dir_name"]
    for _ in range(6):
        if (candidate / 'repositories').is_dir() or (candidate / workspaces_dir).is_dir():
            return candidate
        git_dirs = [d for d in candidate.iterdir() if d.is_dir() and (d / '.git').exists()]
        if len(git_dirs) >= 3:
            return candidate.parent
        candidate = candidate.parent
    return None


def list_sources(root: Path) -> list:
    sources = []
    repos_dir = root / 'repositories'
    if repos_dir.is_dir():
        sources.append({'label': 'repositories', 'path': repos_dir, 'kind': 'repos'})
    workspaces_dir = constants.PROJECT_CONFIG["workspaces_dir_name"]
    ws_dir = root / workspaces_dir
    if ws_dir.is_dir():
        for ws in sorted(ws_dir.iterdir()):
            if not ws.is_dir():
                continue
            has_repos = (ws / 'repositories').is_dir() or any(
                d.is_dir() and (d / '.git').exists() for d in ws.iterdir()
            )
            if has_repos:
                sources.append({'label': ws.name, 'path': ws, 'kind': 'workspace'})
    return sources


def resolve_repos_dir(source: dict) -> Path:
    p = source['path']
    if (p / 'repositories').is_dir():
        return p / 'repositories'
    return p


def scan_repos(repos_dir: Path) -> list:
    runnable = []
    dirs = [repos_dir] if (repos_dir / '.git').exists() else sorted(repos_dir.iterdir())
    for repo_dir in dirs:
        if not repo_dir.is_dir() or not (repo_dir / '.git').exists():
            continue
        svc = detect_service(repo_dir)
        if svc:
            port = assign_port(repo_dir.name)
            env_path = resolve_local_env(repo_dir, repo_dir.name)
            if env_path:
                pv = parse_set_env_sh(env_path).get(svc['port_var'], '')
                if pv.isdigit():
                    port = int(pv)
            runnable.append({
                'name':    repo_dir.name,
                'type':    svc['type'],
                'port':    port,
                'path':    repo_dir,
                'service': svc,
            })
    return runnable
