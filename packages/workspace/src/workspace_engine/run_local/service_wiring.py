"""
workspace_engine.run_local.service_wiring — Lógica de dominio para descubrimiento de servicios, asignación de puertos, URLs y base de datos.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def assign_port(repo_name: str) -> int:
    """Genera un número de puerto local determinista (8000-8999) según hash del repositorio."""
    h = hashlib.md5(repo_name.encode("utf-8")).hexdigest()
    return 8000 + (int(h, 16) % 1000)


_NS_PREFIXES = ("merchants-", "prt-bgal-", "prt-", "core-", "frontend-", "partners-", "api-")
_ENV_SLUGS = ("faf", "csf", "ars", "staging", "dev", "prod", "stg-01", "stg-02", "stg-03")
_ENV_SLUG_RE = re.compile(
    r"-(" + "|".join(sorted(_ENV_SLUGS, key=len, reverse=True)) + r")(-[a-z0-9-]+)?$",
    re.IGNORECASE
)
_URL_RE = re.compile(r"https?://([a-z0-9.-]+)(\/[^\s\"']*)?", re.IGNORECASE)


def service_name_from_subdomain(subdomain: str, strip_env: bool = True) -> str:
    """Extrae el nombre canónico del servicio eliminando prefijos de namespace o hashes de ambiente."""
    s = subdomain.split(".")[0].lower()
    for prefix in _NS_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if strip_env:
        m = _ENV_SLUG_RE.search(s)
        if m:
            s = s[:m.start()]
    return s


def spring_context_path(repo_path: Path) -> str:
    """Extrae el context path de Spring Boot de application.properties o YAML."""
    repo_path = Path(repo_path)
    res_dir = repo_path / "src" / "main" / "resources"
    if not res_dir.is_dir():
        return ""

    for fname in ("application.yml", "application.yaml", "application.properties"):
        fpath = res_dir / fname
        if not fpath.is_file():
            continue
        try:
            content = fpath.read_text(errors="ignore")
            for line in content.splitlines():
                line = line.strip()
                if "context-path" in line and ":" in line:
                    _, _, val = line.partition(":")
                    val = val.strip().strip("'\"")
                    if val and val != "/":
                        return val if val.startswith("/") else f"/{val}"
                elif "server.servlet.context-path=" in line or "server.context-path=" in line:
                    _, _, val = line.partition("=")
                    val = val.strip().strip("'\"")
                    if val and val != "/":
                        return val if val.startswith("/") else f"/{val}"
        except OSError:
            pass
    return ""


def node_health_path(repo_path: Path) -> Optional[str]:
    """Detecta la ruta de health check para servicios Node.js."""
    repo_path = Path(repo_path)
    version_prefix = ""
    health_route = ""

    for p in repo_path.glob("**/*.js"):
        if "node_modules" in p.parts:
            continue
        try:
            txt = p.read_text(errors="ignore")
            v_match = re.search(r"versionPath\s*=\s*['\"]([^'\"]+)['\"]", txt)
            if v_match and not version_prefix:
                version_prefix = v_match.group(1).rstrip("/")
            h_match = re.search(r"['\"](/health[^'\"]*)['\"]", txt)
            if h_match and not health_route:
                health_route = h_match.group(1)
        except OSError:
            pass

    if health_route:
        return f"{version_prefix}{health_route}"
    return None


def service_link(svc_type: str, port: int, repo_path: Optional[Path] = None) -> Tuple[str, str]:
    """Genera etiqueta y URL para acceder a un servicio levantado localmente."""
    if svc_type in ("spring-gradle", "spring-maven", "spring_boot", "spring"):
        ctx = spring_context_path(repo_path) if repo_path else ""
        return "Swagger", f"http://localhost:{port}{ctx}/swagger-ui/index.html"

    if svc_type in ("node", "next", "react", "vue", "vite"):
        hpath = node_health_path(repo_path) if repo_path else None
        if hpath:
            return "Health", f"http://localhost:{port}{hpath}"

    return "App", f"http://localhost:{port}/"


def wire_urls(env_vars: Dict[str, str], running_ports: Dict[str, int]) -> Tuple[Dict[str, str], Dict[str, int]]:
    """Reescribe URLs remotas en variables de entorno para que apunten a puertos locales activos."""
    res = dict(env_vars)
    wired: Dict[str, int] = {}

    for key, val in env_vars.items():
        if not isinstance(val, str) or ("http://" not in val and "https://" not in val):
            continue
        new_val = val
        for m in _URL_RE.finditer(val):
            subdomain = m.group(1)
            path = m.group(2) or ""
            svc_name = service_name_from_subdomain(subdomain, strip_env=True)
            port = running_ports.get(svc_name)
            if port is not None:
                new_val = new_val.replace(m.group(0), f"http://localhost:{port}{path}", 1)
                wired[svc_name] = port
        res[key] = new_val

    return res, wired


def wire_db_urls(src_env: Dict[str, str]) -> Dict[str, str]:
    """Extrae y mapea cadenas de conexión a base de datos (MongoDB, PostgreSQL)."""
    res: Dict[str, str] = {}
    mongo_uris = []
    postgres_uris = []

    for k, v in src_env.items():
        if not isinstance(v, str):
            continue
        if v.startswith("mongodb://") or v.startswith("mongodb+srv://"):
            mongo_uris.append(v)
        elif v.startswith("postgres://") or v.startswith("postgresql://") or v.startswith("jdbc:postgresql://"):
            postgres_uris.append(v)

    if len(set(mongo_uris)) == 1:
        res["SPRING_DATA_MONGODB_URI"] = mongo_uris[0]

    if len(set(postgres_uris)) == 1:
        pg_uri = postgres_uris[0]
        if pg_uri.startswith("postgres://"):
            pg_uri = "postgresql://" + pg_uri[11:]
        if not pg_uri.startswith("jdbc:"):
            pg_uri = f"jdbc:{pg_uri}"
        res["SPRING_DATASOURCE_URL"] = pg_uri

    return res
