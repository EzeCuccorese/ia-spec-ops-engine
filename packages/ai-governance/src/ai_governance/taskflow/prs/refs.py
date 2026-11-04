"""Pull request references found in free text. Pure: no I/O, nothing is ever executed.

Only ``github.com`` is recognised. The text is untrusted (a paste, a command output), so the
patterns accept a narrow character set for owners and repositories and nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

MAX_REFS = 500
_OWNER = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}"
_NAME = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}"
_END = r"(?![0-9A-Za-z])"
_REPO = re.compile(rf"{_OWNER}/{_NAME}")
_PATTERN = re.compile(
    rf"https://github\.com/(?P<uo>{_OWNER})/(?P<ur>{_NAME})/pull/(?P<un>\d{{1,9}}){_END}"
    rf"|(?<![\w/.\-])(?P<o>{_OWNER})/(?P<r>{_NAME})\#(?P<n>\d{{1,9}}){_END}"
    rf"|(?<![\w/.\-])\#(?P<b>\d{{1,9}}){_END}"
)


class PrRef(NamedTuple):
    """A pull request: ``repo`` is ``owner/name`` as written, ``number`` the PR number."""

    repo: str
    number: int

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}".lower()

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}/pull/{self.number}"


@dataclass(frozen=True)
class Scan:
    """What a text holds: the references (in order, no duplicates) and bare ``#N`` skipped."""

    refs: tuple[PrRef, ...]
    bare_skipped: int = 0


def valid_repo(repo: str) -> str:
    """``owner/name`` or ``ValueError``; the caller never builds a query from anything else."""
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise ValueError(f"{repo!r} is not a GitHub repository: use owner/name")
    return repo


def scan(text: str, repo: str | None = None) -> Scan:
    """Find references in ``text``; a bare ``#N`` belongs to ``repo`` (skipped without one)."""
    default = valid_repo(repo) if repo else None
    found: dict[str, PrRef] = {}
    skipped = 0
    for match in _PATTERN.finditer(text):
        group = match.groupdict()
        if group["un"]:
            ref = PrRef(f"{group['uo']}/{group['ur']}", int(group["un"]))
        elif group["n"]:
            ref = PrRef(f"{group['o']}/{group['r']}", int(group["n"]))
        elif default:
            ref = PrRef(default, int(group["b"]))
        else:
            skipped += 1
            continue
        found.setdefault(ref.key, ref)
    return Scan(tuple(found.values()), skipped)


def extract(text: str, repo: str | None = None) -> list[PrRef]:
    """Like ``scan`` but a bare ``#N`` without a repository is an error (CLI exit 1)."""
    result = scan(text, repo)
    if result.bare_skipped:
        bare = _PATTERN.search(_without_qualified(text))
        shown = f"#{bare.group('b')}" if bare and bare.group("b") else "#N"
        raise ValueError(
            f"'{shown}' has no repository: pass --repo owner/name or run it inside a bound repo"
        )
    if len(result.refs) > MAX_REFS:
        raise ValueError(f"too many pull request references ({len(result.refs)} > {MAX_REFS})")
    return list(result.refs)


def _without_qualified(text: str) -> str:
    """The text with qualified references blanked, so the first bare ``#N`` can be named."""
    return _PATTERN.sub(lambda m: m.group(0) if m.group("b") else " " * len(m.group(0)), text)
