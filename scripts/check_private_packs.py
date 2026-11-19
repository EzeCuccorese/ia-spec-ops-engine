"""Reject corporate pack paths in Git and distribution archives."""

from __future__ import annotations

import argparse
import subprocess
import tarfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

PACK_PATHS = (":(glob)**/corporate-rules", ":(glob)**/corporate-rules/**")
PACK_README = "packages/corporate-rules/README.md"


def _git_paths(*args: str) -> set[str]:
    result = subprocess.run(
        ["git", *args, "--", *PACK_PATHS], check=True, capture_output=True, text=True
    )
    return {path for path in result.stdout.split("\0") if path and path != PACK_README}


def _archive_paths(archive: Path) -> Iterable[str]:
    if archive.suffix == ".whl":
        with ZipFile(archive) as wheel:
            return wheel.namelist()
    with tarfile.open(archive) as source:
        return source.getnames()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision", nargs="?", help="Check every added pack path in this Git range")
    parser.add_argument("--dist", type=Path, help="Check wheels and source distributions")
    args = parser.parse_args()
    paths = _git_paths("ls-files", "-z")
    if args.revision:
        paths.update(
            _git_paths(
                "log",
                "-m",
                "--full-history",
                "--format=",
                "--name-only",
                "-z",
                "--diff-filter=ACMRT",
                args.revision,
            )
        )
    if args.dist:
        archives = sorted([*args.dist.glob("*.whl"), *args.dist.glob("*.tar.gz")])
        if not archives:
            raise SystemExit("No distribution archives found.")
        for archive in archives:
            paths.update(
                f"{archive.name}: {path}"
                for path in _archive_paths(archive)
                if "corporate-rules" in PurePosixPath(path).parts
            )
    if paths:
        raise SystemExit(
            "Private packs must stay outside Git and distributions.\n" + "\n".join(sorted(paths))
        )


if __name__ == "__main__":
    main()
