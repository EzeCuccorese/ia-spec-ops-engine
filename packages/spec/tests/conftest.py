from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from spec.core.ownership import OwnershipManifest
from spec.core.write import SafeWriter

LEGACY_CLAUDE_BLOCK = "<!-- spec:governance -->\n@AGENTS.md\n<!-- /spec:governance -->\n"


@pytest.fixture
def legacy_claude_md() -> Callable[[Path], Path]:
    """Writes the owned CLAUDE.md that `spec agent install claude` created before AGENTS.md
    became the only instructions file."""

    def seed(root: Path) -> Path:
        SafeWriter(root, OwnershipManifest(root)).write("CLAUDE.md", LEGACY_CLAUDE_BLOCK)
        return root / "CLAUDE.md"

    return seed
