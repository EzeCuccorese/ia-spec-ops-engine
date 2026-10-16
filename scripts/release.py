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
from collections.abc import Callable, Iterable
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


PYPROJECT_VERSION = re.compile(r'^version = "[^"]*"$', re.MULTILINE)
INIT_VERSION = re.compile(r'^__version__ = "[^"]*"$', re.MULTILINE)

# Files that carry the project version. spec reads its version from package metadata,
# so only its pyproject needs the bump.
PYPROJECT_FILES = (
    "pyproject.toml",
    "packages/ai-governance/pyproject.toml",
    "packages/spec/pyproject.toml",
    "packages/workspace/pyproject.toml",
)
INIT_FILES = (
    "packages/ai-governance/src/ai_governance/__init__.py",
    "packages/workspace/src/workspace_engine/__init__.py",
)


def write_version_files(root: Path, version: str) -> list[str]:
    """Write ``version`` into every version field and return the files that changed."""
    parse_version(version)
    changed: list[str] = []
    for relative in PYPROJECT_FILES:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        new_text, count = PYPROJECT_VERSION.subn(f'version = "{version}"', text, count=1)
        if count != 1:
            raise ValueError(f"no version line found in {relative}")
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(relative)
    for relative in INIT_FILES:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        new_text, count = INIT_VERSION.subn(f'__version__ = "{version}"', text, count=1)
        if count != 1:
            raise ValueError(f"no __version__ line found in {relative}")
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(relative)
    return changed


def prepend_changelog(changelog: Path, section: str) -> None:
    """Insert a release section above the previous releases (creating the file if needed)."""
    header = "# Changelog\n\n"
    existing = changelog.read_text(encoding="utf-8") if changelog.exists() else header
    body = existing[len(header) :] if existing.startswith(header) else existing
    changelog.write_text(f"{header}{section}\n{body.lstrip()}", encoding="utf-8")


def extract_section(changelog: Path, version: str) -> str:
    """Return the body of one version's section (without its heading)."""
    lines = changelog.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {version} "))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end]).strip() + "\n"


def cmd_next(args: argparse.Namespace) -> int:
    current = args.version_file.read_text(encoding="utf-8").strip()
    commits = read_commits(args.log.read_text(encoding="utf-8"))
    new = next_version(current, commits)
    if new is None:
        print("no release needed")
        return 0
    print(new)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Write the new version everywhere and prepend its changelog section."""
    version = args.version
    root = args.root
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    write_version_files(root, version)
    if args.notes is not None:
        notes = args.notes.read_text(encoding="utf-8").strip()
        if not notes:
            raise ValueError("--notes is empty; omit it to use the commit list instead")
        section = f"## {version} - {args.date}\n\n{notes}\n"
    elif args.log is not None:
        commits = read_commits(args.log.read_text(encoding="utf-8"))
        section = changelog_section(version, args.date, commits)
    else:
        raise ValueError("apply needs --notes or --log")
    prepend_changelog(root / "CHANGELOG.md", section.rstrip() + "\n")
    print(f"applied {version}")
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    """Print one release's changelog body, used as the GitHub Release notes."""
    print(extract_section(args.changelog, args.version), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    nxt = sub.add_parser("next", help="print the next version, or 'no release needed'")
    nxt.add_argument("--version-file", type=Path, default=Path("VERSION"))
    nxt.add_argument(
        "--log",
        type=Path,
        required=True,
        help="file with `git log --format=%%s%%n%%b%%x00 <last-tag>..HEAD` output",
    )
    nxt.set_defaults(handler=cmd_next)

    app = sub.add_parser("apply", help="write a version into all files and the changelog")
    app.add_argument("version", help="MAJOR.MINOR.PATCH")
    app.add_argument("--root", type=Path, default=Path("."))
    app.add_argument("--date", required=True, help="YYYY-MM-DD for the changelog heading")
    app.add_argument("--log", type=Path, help="commit log, used when --notes is missing")
    app.add_argument("--notes", type=Path, help="markdown section body (AI notes)")
    app.set_defaults(handler=cmd_apply)

    notes = sub.add_parser("notes", help="print one version's changelog body")
    notes.add_argument("version")
    notes.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    notes.set_defaults(handler=cmd_notes)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
