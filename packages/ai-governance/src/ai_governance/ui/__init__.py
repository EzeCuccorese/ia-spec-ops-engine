"""Local visual dashboard for Taskflow and Second Brain."""

from __future__ import annotations

from .app import create_app
from .security import SessionSecurity

__all__ = ["SessionSecurity", "create_app"]
