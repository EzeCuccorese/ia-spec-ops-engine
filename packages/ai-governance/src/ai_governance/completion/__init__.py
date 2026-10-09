"""zsh <TAB> completion for the engine's CLIs (ai-governance, ws, spec).

Each installed tool is walked inside its own interpreter (``walker.py``), rendered to a
static ``_<tool>`` function (``zsh.py``) and owned by the installer: written on
``install --scope user`` and refreshed on ``update``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..install.agents import Artifact, BlockArtifact, FileArtifact
from ..paths import data_dir
from .zsh import render

TOOLS = ("ai-governance", "ws", "spec")
WALKER = Path(__file__).with_name("walker.py")
WALK_TIMEOUT = 60.0


def zsh_dir() -> Path:
    return data_dir() / "zsh"


def zshrc() -> Path:
    return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshrc"


def _interpreter(binary: str) -> list[str] | None:
    """The console script's own Python, read from its shebang."""
    try:
        with open(binary, encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    return first[2:].split() or None


def walk(prog: str) -> dict[str, Any] | None:
    """The tool's argparse tree, or None when it is not installed or cannot be walked."""
    binary = shutil.which(prog)
    interpreter = _interpreter(binary) if binary else None
    if interpreter is None:
        return None
    try:
        result = subprocess.run(
            [*interpreter, "-I", str(WALKER), prog],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            cwd=tempfile.gettempdir(),
            timeout=WALK_TIMEOUT,
            check=False,
        )
        tree = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return tree if isinstance(tree, dict) and tree.get("subcommands") else None


def artifacts() -> list[Artifact]:
    """One `_<tool>` file per installed tool plus the fpath line in ~/.zshrc.

    Empty when the user has no ~/.zshrc (not a zsh user) or no tool could be walked.
    """
    rc = zshrc()
    if not rc.is_file():
        return []
    files: list[Artifact] = [
        FileArtifact(zsh_dir() / f"_{prog}", render(tree))
        for prog in TOOLS
        if (tree := walk(prog)) is not None
    ]
    if not files:
        return []
    body = (
        "# <TAB> completion for ai-governance, ws and spec (must run before compinit)\n"
        f'fpath=("{zsh_dir()}" $fpath)'
    )
    return [*files, BlockArtifact(rc, body, comment="#", prepend=True)]


def script(prog: str) -> str | None:
    tree = walk(prog)
    return render(tree) if tree is not None else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-governance completion",
        description="Print a zsh completion script (install/update write them for you).",
    )
    parser.add_argument("shell", choices=["zsh"])
    parser.add_argument("tool", nargs="?", choices=TOOLS, default="ai-governance")
    args = parser.parse_args(argv)
    text = script(args.tool)
    if text is None:
        print(f"{args.tool} is not installed or exposes no commands.", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0
