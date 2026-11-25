"""Loopback, Host/Origin, and per-session CSRF token guards for the local UI server."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_TOKEN_META_NAME = "ai-gov-token"


@dataclass(frozen=True)
class SessionSecurity:
    host: str
    port: int
    token: str

    @classmethod
    def generate(cls, host: str = "127.0.0.1", port: int = 7474) -> SessionSecurity:
        return cls(host=validate_loopback_host(host), port=port, token=secrets.token_hex(32))


def validate_loopback_host(host: str) -> str:
    cleaned = host.strip().lower()
    if cleaned not in LOOPBACK_HOSTS:
        raise ValueError(f"UI server only binds to loopback hosts (got {host!r})")
    return cleaned


def is_allowed_host(header: str, port: int) -> bool:
    if not header:
        return False
    host = header.strip().lower()
    allowed = {"127.0.0.1", "localhost", "[::1]", "testserver"}
    if host in allowed:
        return True
    name, sep, raw_port = host.rpartition(":")
    if not sep or not raw_port.isdigit():
        return False
    return name in allowed and int(raw_port) == port


def is_allowed_origin(origin: str) -> bool:
    parsed = urlparse(origin.strip())
    return parsed.scheme == "http" and (parsed.hostname or "").lower() in LOOPBACK_HOSTS


def _check_mutation(request: Request, token: str) -> JSONResponse | None:
    if request.method not in MUTATING_METHODS:
        return None
    origin = request.headers.get("origin", "")
    if origin and not is_allowed_origin(origin):
        return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
    supplied = request.headers.get("x-ui-token", "")
    if not secrets.compare_digest(supplied, token):
        return JSONResponse({"detail": "Missing or invalid X-UI-Token"}, status_code=403)
    return None


def install_security_middleware(app: FastAPI, security: SessionSecurity) -> None:
    """Reject non-loopback Host headers and unauthenticated mutating requests."""

    @app.middleware("http")
    async def _guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not is_allowed_host(request.headers.get("host", ""), security.port):
            return JSONResponse({"detail": "Invalid Host header"}, status_code=403)
        if denied := _check_mutation(request, security.token):
            return denied
        return await call_next(request)


def inject_token_meta(html: str, token: str) -> str:
    """Inject the per-session CSRF token into ``<head>`` without modifying disk files."""
    tag = f'<meta name="{_TOKEN_META_NAME}" content="{token}" />'
    if "</head>" in html:
        return html.replace("</head>", f"  {tag}\n  </head>", 1)
    return f"{tag}\n{html}"
