"""Compute the next project version from Conventional Commit subjects.

The whole repository ships as one version. The version lives in the ``VERSION`` file,
the release bumps it inside a PR, and the tag ``vX.Y.Z`` is created when that PR merges.

Rules (pre-1.0 is not used: the first release is 1.0.0):
  * ``type!:`` or a ``BREAKING CHANGE`` footer  -> major
  * ``feat:``                                    -> minor
  * ``fix:`` / ``perf:``                         -> patch
  * anything else (chore, docs, test, ci, ...)   -> no release
  * ``chore(release): ...`` commits are ignored so the release commit never re-triggers.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
SUBJECT = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?(?P<bang>!)?: (?P<desc>.+)$")
RELEASE_SUBJECT = re.compile(r"^chore\(release\): ")

SECTIONS: dict[str, str] = {
    "breaking": "Breaking changes",
    "feat": "Features",
    "fix": "Fixes",
    "perf": "Performance",
}


@dataclass(frozen=True)
class Commit:
    subject: str
    body: str = ""


@dataclass(frozen=True)
class ParsedCommit:
    kind: str
    description: str
    breaking: bool


def parse_version(text: str) -> tuple[int, int, int]:
    match = SEMVER.match(text.strip())
    if match is None:
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {text!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def parse_commit(commit: Commit) -> ParsedCommit | None:
    """Return the parsed commit, or None when it is a release commit or not conventional."""
    if RELEASE_SUBJECT.match(commit.subject):
        return None
    match = SUBJECT.match(commit.subject.strip())
    if match is None:
        return None
    breaking = bool(match.group("bang")) or "BREAKING CHANGE" in commit.body
    return ParsedCommit(match.group("type"), match.group("desc"), breaking)


def bump_kind(commits: Iterable[Commit]) -> str | None:
    """Return "major", "minor", "patch" or None for the strongest change in the list."""
    kinds = set()
    for commit in commits:
        parsed = parse_commit(commit)
        if parsed is None:
            continue
        if parsed.breaking:
            kinds.add("major")
        elif parsed.kind == "feat":
            kinds.add("minor")
        elif parsed.kind in {"fix", "perf"}:
            kinds.add("patch")
    for level in ("major", "minor", "patch"):
        if level in kinds:
            return level
    return None


def next_version(current: str, commits: Iterable[Commit]) -> str | None:
    """Return the next version, or None when no commit calls for a release."""
    kind = bump_kind(commits)
    if kind is None:
        return None
    major, minor, patch = parse_version(current)
    if kind == "major":
        return format_version((major + 1, 0, 0))
    if kind == "minor":
        return format_version((major, minor + 1, 0))
    return format_version((major, minor, patch + 1))


def changelog_section(version: str, date: str, commits: Iterable[Commit]) -> str:
    """Build a changelog section from commit subjects. Used when the AI notes are unavailable."""
    grouped: dict[str, list[str]] = {title: [] for title in SECTIONS.values()}
    for commit in commits:
        parsed = parse_commit(commit)
        if parsed is None:
            continue
        if parsed.breaking:
            grouped[SECTIONS["breaking"]].append(parsed.description)
        elif parsed.kind in SECTIONS:
            grouped[SECTIONS[parsed.kind]].append(parsed.description)

    lines = [f"## {version} - {date}", ""]
    for title, items in grouped.items():
        if not items:
            continue
        lines.append(f"### {title}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def read_commits(git_log: str) -> list[Commit]:
    """Parse ``git log --format=%s%n%b%x00`` output into commits."""
    commits: list[Commit] = []
    for record in git_log.split("\x00"):
        if not record.strip():
            continue
        subject, _, body = record.strip("\n").partition("\n")
        commits.append(Commit(subject=subject.strip(), body=body))
    return commits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version-file", type=Path, default=Path("VERSION"))
    parser.add_argument(
        "--log",
        type=Path,
        required=True,
        help="file with `git log --format=%%s%%n%%b%%x00 <last-tag>..HEAD` output",
    )
    args = parser.parse_args(argv)

    current = args.version_file.read_text(encoding="utf-8").strip()
    commits = read_commits(args.log.read_text(encoding="utf-8"))
    new = next_version(current, commits)
    if new is None:
        print("no release needed")
        return 0
    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
