"""Which GitHub repository a checkout belongs to (to place a bare ``#N``).

Only ``github.com`` counts. An SSH alias such as ``github-cucco`` is accepted when
``ssh -G <alias>`` (which reads the configuration and never connects) prints
``hostname github.com``; a missing ``ssh`` or any other host means "not GitHub".
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from .refs import valid_repo

HostResolver = Callable[[str], str | None]
_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_HTTPS = re.compile(r"https://(?:[^/@\s]+@)?github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?")
_SSH = re.compile(
    r"(?:ssh://)?(?:[A-Za-z0-9._-]+@)?(?P<host>[A-Za-z0-9][A-Za-z0-9._-]*)[:/](?P<o>[^/\s:]+)/(?P<n>[^/\s]+?)(?:\.git)?/?"
)
GIT_TIMEOUT = 10


def ssh_hostname(alias: str) -> str | None:
    """The real host behind an SSH alias, per ``ssh -G`` (no connection is made)."""
    if not _ALIAS.fullmatch(alias):
        return None
    try:
        done = subprocess.run(  # noqa: S603, S607 - fixed argv, validated alias, no shell
            ["ssh", "-G", alias],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in done.stdout.splitlines():
        if line.startswith("hostname "):
            return line.split(None, 1)[1].strip().lower()
    return None


def parse_remote(url: str, resolve: HostResolver = ssh_hostname) -> str | None:
    """``owner/name`` when ``url`` points at github.com (directly or via an alias), else None."""
    url = url.strip()
    if url.startswith("https://"):
        match = _HTTPS.fullmatch(url)
        return _repo(match.group(1), match.group(2)) if match else None
    match = _SSH.fullmatch(url)
    if not match or url.startswith(("http://", "file://", "/")):
        return None
    host = match["host"].lower()
    if host != "github.com" and resolve(host) != "github.com":
        return None
    return _repo(match["o"], match["n"])


def _repo(owner: str, name: str) -> str | None:
    try:
        return valid_repo(f"{owner}/{name}")
    except ValueError:
        return None


def remote_url(path: Path) -> str:
    """``remote.origin.url`` of the checkout at ``path`` ('' when there is none)."""
    try:
        done = subprocess.run(  # noqa: S603, S607 - fixed argv, no shell
            ["git", "config", "--get", "remote.origin.url"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def infer_repo(paths: Iterable[Path], resolve: HostResolver = ssh_hostname) -> str:
    """The one GitHub repository the bound checkouts share, or ``ValueError`` naming why not."""
    repos: dict[str, str] = {}
    for path in paths:
        found = parse_remote(remote_url(path), resolve)
        if found:
            repos.setdefault(found.lower(), found)
    if len(repos) > 1:
        raise ValueError(
            f"ambiguous repository: {' and '.join(sorted(repos.values()))}; pass --repo"
        )
    if not repos:
        raise ValueError("no GitHub origin among the bound repos: pass --repo owner/name")
    return next(iter(repos.values()))
