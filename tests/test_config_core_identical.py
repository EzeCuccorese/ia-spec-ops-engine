"""The shared config core is copied, not imported: the three copies must never drift."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages"
COPIES = (
    ROOT / "ai-governance" / "src" / "ai_governance" / "_config_core.py",
    ROOT / "workspace" / "src" / "workspace_engine" / "_config_core.py",
    ROOT / "spec" / "src" / "spec" / "_config_core.py",
)


def test_config_core_copies_are_byte_identical() -> None:
    reference = COPIES[0].read_bytes()
    drifted = [str(path) for path in COPIES[1:] if path.read_bytes() != reference]
    assert not drifted, f"copy of {COPIES[0].name} out of sync (copy it over): {drifted}"
