"""Daily price-table refresh as a macOS LaunchAgent. Retired: the user scope no longer
installs it, and installs and uninstalls stop and remove any copy left on disk.

The plist was an owned file (ledger-managed like the completions); launchd is told about
it only for the real ``~/Library/LaunchAgents`` folder, never for an overridden one.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from ..paths import state_dir
from .agents import Artifact, FileArtifact

LABEL = "com.ai-governance.prices-update"
LEGACY_LABEL = "com.cucco.claude-uso-precios"  # hand-made agent this one replaces
HOUR = 6
LAUNCH_AGENTS_ENV = "AI_GOVERNANCE_LAUNCH_AGENTS_DIR"


def supported() -> bool:
    return sys.platform == "darwin"


def _live() -> bool:
    """True when the plists live in the real folder launchd reads."""
    return LAUNCH_AGENTS_ENV not in os.environ


def launch_agents_dir() -> Path:
    explicit = os.environ.get(LAUNCH_AGENTS_ENV)
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(label: str = LABEL) -> Path:
    return launch_agents_dir() / f"{label}.plist"


def render() -> str:
    candidate = Path(sys.executable).parent / "ai-governance"
    executable = (
        shutil.which("ai-governance")
        or (str(candidate) if candidate.is_file() else None)
        or str(Path.home() / ".local" / "bin" / "ai-governance")
    )
    log = str(state_dir() / "telemetry" / "prices-update.log")
    document = {
        "Label": LABEL,
        "ProgramArguments": [executable, "telemetry", "prices", "update"],
        "RunAtLoad": False,
        "StartCalendarInterval": {"Hour": HOUR, "Minute": 0},
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    return plistlib.dumps(document).decode("utf-8")


def artifacts() -> list[Artifact]:
    return [FileArtifact(plist_path(), render())] if supported() else []


def _launchctl(*args: str) -> None:
    subprocess.run(["launchctl", *args], capture_output=True, check=False)  # noqa: S603, S607


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _unload(label: str) -> None:
    _launchctl("bootout", f"{_domain()}/{label}")


def _retire_legacy() -> None:
    _unload(LEGACY_LABEL)
    plist_path(LEGACY_LABEL).unlink(missing_ok=True)


def load() -> None:
    """(Re)loads the agent and retires the hand-made one it replaces."""
    if not (supported() and _live()):
        return
    _retire_legacy()
    if plist_path().is_file():
        # launchd cannot open the log files when their folder is missing.
        (state_dir() / "telemetry").mkdir(parents=True, exist_ok=True)
        _unload(LABEL)
        _launchctl("bootstrap", _domain(), str(plist_path()))


def unload() -> None:
    """Stops and removes the agent, even an orphan the ledger does not know about,
    and retires the hand-made one it replaced."""
    if supported() and _live():
        _unload(LABEL)
        plist_path().unlink(missing_ok=True)
        _retire_legacy()
