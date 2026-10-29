"""``code_stamp``: what code a round, verdict or approval was about.

Unlike ``spec``'s full-tree walk, the fingerprint hashes ``HEAD`` plus every path git
reports as changed (staged, unstaged, untracked, both sides of renames), with content,
mode and symlink target. That covers the same edits without reading ``node_modules``-sized
trees, and ignored files never invalidate a verdict.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

from .models import JsonDict, now_iso

GIT_TIMEOUT = 30
REMOTE_TIMEOUT = 20


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git {' '.join(args)}: {exc}") from exc
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def changed_paths(repo: Path, base: str = "") -> list[str]:
    """Paths touched by commits since ``base`` plus everything uncommitted (renames: both)."""
    paths: set[str] = set()
    if base:
        for line in git(repo, "diff", "--name-status", "-M", f"{base}...HEAD").splitlines():
            paths.update(line.split("\t")[1:])
    entries = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.add(entry[3:])
        if entry[0] in "RC":  # porcelain -z: the rename source follows as its own field
            paths.add(entries[index])
            index += 1
    return sorted(paths)


def _path_digest(repo: Path, rel: str) -> str:
    path = repo / rel
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "deleted"
    if stat.S_ISLNK(info.st_mode):
        return "link:" + os.readlink(path)
    if not stat.S_ISREG(info.st_mode):
        return "other"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{oct(info.st_mode & 0o777)}:{digest}"


def head_sha(repo: Path) -> str:
    """HEAD, or ``UNBORN`` in a repository without commits (so a new repo does not crash)."""
    try:
        return git(repo, "rev-parse", "HEAD").strip()
    except GitError:
        return "UNBORN"


def tree_fingerprint(repo: Path) -> str:
    hasher = hashlib.sha256(head_sha(repo).encode())
    for rel in changed_paths(repo):
        hasher.update(f"\n{rel}:{_path_digest(repo, rel)}".encode())
    # Staged blob ids: re-staging different content keeps HEAD and the work tree, not these.
    hasher.update(git(repo, "diff", "--cached", "--raw", "--full-index").encode())
    hasher.update(git(repo, "submodule", "status", "--recursive").encode())
    return hasher.hexdigest()


def remote_sha(repo: Path, branch: str, remote: str = "origin") -> tuple[str, str]:
    """(sha, status). Network or auth failure is ``unverified``, never "unchanged"."""
    try:
        out = git(repo, "ls-remote", remote, f"refs/heads/{branch}", timeout=REMOTE_TIMEOUT)
    except GitError:
        return "", "unverified"
    sha = out.split()[0] if out.split() else ""
    return sha, "verified" if sha else "missing"


def merge_base(repo: Path, branch: str) -> str:
    for ref in (f"origin/{branch}", branch):
        try:
            return git(repo, "merge-base", "HEAD", ref).strip()
        except GitError:
            continue
    return ""


def repo_stamp(repo: Path, *, integration_branch: str = "", check_remote: bool = False) -> JsonDict:
    head = head_sha(repo)
    stamp: JsonDict = {
        "repo": str(repo),
        "branch": git(repo, "branch", "--show-current").strip(),
        "head": head,
        "dirty": bool(git(repo, "status", "--porcelain").strip()),
        "fingerprint": tree_fingerprint(repo),
    }
    if integration_branch:
        stamp["integration_branch"] = integration_branch
        stamp["base"] = merge_base(repo, integration_branch)
        if check_remote:
            sha, status = remote_sha(repo, integration_branch)
            stamp.update(integration_sha=sha, remote_status=status)
    return stamp


def code_stamp(repos: list[JsonDict], policy_digest: str, check_remote: bool = False) -> JsonDict:
    """Stamp of every bound repository; ``key`` changes when any of them or the policy does."""
    stamps = [
        repo_stamp(
            Path(repo["path"]),
            integration_branch=str(repo.get("integration_branch", "")),
            check_remote=check_remote,
        )
        for repo in repos
    ]
    hasher = hashlib.sha256(policy_digest.encode())
    for item in stamps:
        # The base is local (merge-base with the fetched integration branch): a rebase or a
        # new fetch changes it; the network-only ls-remote SHA is reported, not hashed.
        hasher.update(f"\n{item['repo']}:{item['fingerprint']}:{item.get('base', '')}".encode())
    return {
        "key": hasher.hexdigest()[:16],
        "repos": stamps,
        "policy": policy_digest,
        "at": now_iso(),
    }
