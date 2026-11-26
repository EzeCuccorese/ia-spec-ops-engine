"""FastAPI application factory for the Taskflow & Second Brain visual dashboard."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..brain.store import BrainStore
from ..taskflow.store import TaskStore
from .events import stream_store_events
from .launcher import list_live_workers
from .routes_brain import build_brain_router
from .routes_tasks import build_tasks_router
from .security import SessionSecurity, inject_token_meta, install_security_middleware

_MISSING_UI_HTML = """<!doctype html>
<html><head><title>ai-governance UI</title></head>
<body style="font-family:system-ui;background:#070b14;color:#e2e8f0;padding:2rem;">
  <h1>Visual Dashboard static assets not built</h1>
  <p>Run <code>cd packages/ai-governance/ui && npm ci && npm run build</code> to compile the UI.</p>
</body></html>"""


def default_static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def create_app(
    security: SessionSecurity,
    *,
    task_store_factory: Callable[[], TaskStore] = TaskStore,
    brain_store_factory: Callable[[], BrainStore] = BrainStore,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create the FastAPI app serving API routes and the compiled React SPA."""
    app = FastAPI(title="ai-governance Visual Dashboard", version=__version__, docs_url=None)
    install_security_middleware(app, security)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "host": security.host,
            "port": security.port,
        }

    @app.get("/api/orca/workers")
    def orca_workers() -> dict[str, object]:
        return list_live_workers()

    @app.get("/api/events")
    def store_events(max_events: int | None = None) -> StreamingResponse:
        clamped = max(1, min(max_events, 100)) if max_events is not None else None
        return StreamingResponse(
            stream_store_events(
                task_store_factory().root,
                brain_store_factory().root,
                max_events=clamped,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(build_tasks_router(task_store_factory, brain_store_factory))
    app.include_router(build_brain_router(brain_store_factory, task_store_factory))

    resolved_static = static_dir or default_static_dir()
    assets_dir = resolved_static / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="ui-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_index(full_path: str) -> Response:
        if full_path.startswith("api/"):
            return Response(status_code=404)
        index_file = resolved_static / "index.html"
        if not index_file.is_file():
            return HTMLResponse(_MISSING_UI_HTML, status_code=503)
        html = inject_token_meta(index_file.read_text(encoding="utf-8"), security.token)
        return HTMLResponse(html)

    return app
