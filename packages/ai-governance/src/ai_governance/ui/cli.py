"""CLI entry point for ``ai-governance ui`` (start, stop, status, open, serve)."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from ..output import emit_json, emit_status
from .app import create_app
from .daemon import is_running, open_dashboard, start_daemon, stop_daemon
from .security import SessionSecurity, validate_loopback_host


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance ui",
        description="Local visual dashboard for Taskflow and Second Brain",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    start_p = sub.add_parser("start", help="Start the visual dashboard server")
    start_p.add_argument("--host", default="127.0.0.1")
    start_p.add_argument("--port", type=int, default=7474)
    start_p.add_argument("--background", action="store_true", help="Run as a background daemon")

    sub.add_parser("stop", help="Stop the background dashboard daemon")

    status_p = sub.add_parser("status", help="Show dashboard daemon status")
    status_p.add_argument("--json", action="store_true")

    open_p = sub.add_parser("open", help="Open the running dashboard in browser or Orca")
    open_p.add_argument("--orca", action="store_true", help="Open inside Orca embedded browser")

    serve_p = sub.add_parser("serve", help=argparse.SUPPRESS)
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=7474)
    serve_p.add_argument("--token", default="")
    return parser


def _cmd_start(args: argparse.Namespace) -> int:
    host = validate_loopback_host(args.host)
    if args.background:
        info = start_daemon(host=host, port=args.port)
        emit_status("ok", f"Dashboard running at {info.url} (pid {info.pid})")
        return 0
    sec = SessionSecurity.generate(host, args.port)
    emit_status("ok", f"Serving dashboard at http://{host}:{args.port}")
    uvicorn.run(create_app(sec), host=host, port=args.port, log_level="info")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    host = validate_loopback_host(args.host)
    token = args.token or os.environ.get("AI_GOVERNANCE_UI_TOKEN", "")
    sec = (
        SessionSecurity(host=host, port=args.port, token=token)
        if token
        else SessionSecurity.generate(host, args.port)
    )
    uvicorn.run(create_app(sec), host=host, port=args.port, log_level="info")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    info = is_running()
    if args.json:
        payload = (
            {
                "running": True,
                "pid": info.pid,
                "url": info.url,
                "started_at": info.started_at,
                "log_path": info.log_path,
            }
            if info
            else {"running": False}
        )
        emit_json(payload)
        return 0
    if info is None:
        emit_status("info", "Dashboard is stopped")
        return 0
    emit_status("ok", f"Dashboard running at {info.url} (pid {info.pid})")
    return 0


def _cmd_open(args: argparse.Namespace) -> int:
    info = is_running()
    if info is None:
        emit_status(
            "error", "Dashboard is not running; start it with `ai-governance ui start --background`"
        )
        return 1
    target = open_dashboard(info.url, use_orca=bool(args.orca))
    emit_status("ok", f"Opened {info.url} in {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        if args.action == "start":
            return _cmd_start(args)
        if args.action == "serve":
            return _cmd_serve(args)
        if args.action == "stop":
            stopped = stop_daemon()
            emit_status(
                "ok" if stopped else "info",
                "Dashboard stopped" if stopped else "Dashboard was not running",
            )
            return 0
        if args.action == "status":
            return _cmd_status(args)
        return _cmd_open(args)
    except ValueError as exc:
        emit_status("error", str(exc))
        return 2
