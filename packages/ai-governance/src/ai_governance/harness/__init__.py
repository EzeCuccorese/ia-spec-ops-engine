"""Deterministic tools index and self-wiring block for AGENTS.md.

This package does not write host configuration (e.g. ``~/.claude/settings.json``).
It renders and injects a documentation block into ``AGENTS.md`` that tells the
agent how to self-configure its own runtime, and offers a read-only ``doctor``
to verify the resulting state.
"""

from __future__ import annotations
