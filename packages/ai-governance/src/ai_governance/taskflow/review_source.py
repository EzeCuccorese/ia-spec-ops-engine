"""What a review round reads: a pull request captured at one head commit.

``snapshot_pull_request`` writes, under one directory of the task: the PR metadata
(``pr.json``), its diff (``pr.diff``), the unresolved review threads (``threads.json``), a
read-only checkout of the head commit (``src/``) and the files that mention each changed file
(``references.md``). Reviewer and judge read those files and nothing else, so a round never
depends on a local working tree and needs no GitHub access.

Everything here reads from GitHub (``gh``) and git; nothing writes to the pull request.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .control import DispatchError
from .models import JsonDict
from .stamp import GitError, git
from .store import atomic_write_text

PR_URL = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)(?:[/?#].*)?$")
GH_TIMEOUT = 60
FETCH_TIMEOUT = 600
THREAD_PAGE_LIMIT = 10
MAX_REFERENCED_FILES = 40
MAX_HITS_PER_FILE = 15
MIN_STEM_LENGTH = 4
# File stems too common to say anything about who uses a file.
GENERIC_STEMS = frozenset(
    {"index", "main", "init", "__init__", "utils", "util", "types", "test", "tests", "config"}
    | {"constants", "models", "model", "readme", "setup", "base", "common", "helpers", "schema"}
)
META_FIELDS = (
    "number,title,url,state,isDraft,headRefOid,baseRefOid,baseRefName,headRefName,author,body,files"
)
ACTIVITY_FIELDS = "isDraft,reviews,comments"
THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 30) {
            nodes { author { login } body url createdAt }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class PullRef:
    """A pull request named by its URL."""

    owner: str
    repo: str
    number: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def key(self) -> str:
        """Directory-safe name of this pull request inside a review."""
        return re.sub(r"[^A-Za-z0-9_.-]", "-", f"{self.owner}-{self.repo}-{self.number}")

    @property
    def url(self) -> str:
        return f"https://github.com/{self.slug}/pull/{self.number}"


@dataclass(frozen=True)
class PullSnapshot:
    """One pull request captured at ``head_sha`` under ``directory``."""

    ref: PullRef
    title: str
    head_sha: str
    base_ref: str
    is_draft: bool
    directory: Path

    @property
    def meta_file(self) -> Path:
        return self.directory / "pr.json"

    @property
    def diff_file(self) -> Path:
        return self.directory / "pr.diff"

    @property
    def threads_file(self) -> Path:
        return self.directory / "threads.json"

    @property
    def references_file(self) -> Path:
        return self.directory / "references.md"

    @property
    def source(self) -> Path:
        return self.directory / "src"


def parse_pr_url(url: str) -> PullRef:
    match = PR_URL.match(url.strip())
    if match is None:
        raise DispatchError(
            f"not a GitHub pull request URL: {url} (expected https://github.com/<owner>/<repo>/pull/<n>)"
        )
    return PullRef(match.group(1), match.group(2), int(match.group(3)))


def _gh(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=GH_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DispatchError(f"gh {args[0]} could not run: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr.strip().splitlines() or [str(proc.returncode)])[0]
        raise DispatchError(f"gh {' '.join(args[:2])} failed: {detail}")
    return proc.stdout


def _gh_json(*args: str) -> JsonDict:
    try:
        found = json.loads(_gh(*args))
    except ValueError as exc:
        raise DispatchError(f"gh {' '.join(args[:2])} did not print JSON") from exc
    if not isinstance(found, dict):
        raise DispatchError(f"gh {' '.join(args[:2])} printed an unexpected JSON shape")
    return found


def viewer_login() -> str:
    """The GitHub account ``gh`` acts as."""
    return _gh("api", "user", "--jq", ".login").strip()


def _thread_page(ref: PullRef, cursor: str) -> JsonDict:
    args = ["api", "graphql", "-f", f"query={THREADS_QUERY}", "-f", f"owner={ref.owner}"]
    args += ["-f", f"name={ref.repo}", "-F", f"number={ref.number}"]
    if cursor:
        args += ["-f", f"after={cursor}"]
    data = _gh_json(*args)
    try:
        page = data["data"]["repository"]["pullRequest"]["reviewThreads"]
    except (KeyError, TypeError) as exc:
        raise DispatchError(f"GitHub did not return the review threads of {ref.url}") from exc
    if not isinstance(page, dict) or not isinstance(page.get("nodes"), list):
        raise DispatchError(f"GitHub returned malformed review threads for {ref.url}")
    return page


def _all_threads(ref: PullRef) -> tuple[list[JsonDict], bool]:
    """Every review thread and whether the listing was cut short (never silently)."""
    nodes: list[JsonDict] = []
    cursor = ""
    for _ in range(THREAD_PAGE_LIMIT):
        page = _thread_page(ref, cursor)
        nodes += [node for node in page["nodes"] if isinstance(node, dict)]
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return nodes, False
        cursor = str(info.get("endCursor") or "")
    return nodes, True


def _thread_comments(node: JsonDict) -> list[JsonDict]:
    raw = (node.get("comments") or {}).get("nodes") or []
    return [
        {
            "author": str((item.get("author") or {}).get("login") or ""),
            "body": str(item.get("body") or ""),
            "url": str(item.get("url") or ""),
            "at": str(item.get("createdAt") or ""),
        }
        for item in raw
        if isinstance(item, dict)
    ]


def open_threads(ref: PullRef) -> JsonDict:
    """Unresolved review threads, each with a short id (``t1``...) the judge refers to."""
    nodes, truncated = _all_threads(ref)
    unresolved = [node for node in nodes if not node.get("isResolved")]
    return {
        "truncated": truncated,
        "threads": [
            {
                "id": f"t{index}",
                "node_id": str(node.get("id") or ""),
                "path": str(node.get("path") or ""),
                "line": node.get("line"),
                "outdated": bool(node.get("isOutdated")),
                "comments": _thread_comments(node),
            }
            for index, node in enumerate(unresolved, start=1)
        ],
    }


def _clone_url(ref: PullRef) -> str:
    try:
        protocol = _gh("config", "get", "git_protocol", "--host", "github.com").strip()
    except DispatchError:
        protocol = ""
    if protocol == "ssh":
        return f"git@github.com:{ref.slug}.git"
    return f"https://github.com/{ref.slug}.git"


def checkout_source(ref: PullRef, head_sha: str, dest: Path) -> None:
    """A checkout of the PR head commit alone (depth 1), refused when the PR moved meanwhile."""
    dest.mkdir(parents=True, exist_ok=False)
    try:
        git(dest, "init", "--quiet")
        git(
            dest,
            *("fetch", "--quiet", "--depth", "1", _clone_url(ref)),
            f"refs/pull/{ref.number}/head",
            timeout=FETCH_TIMEOUT,
        )
        fetched = git(dest, "rev-parse", "FETCH_HEAD").strip()
        if fetched != head_sha:
            raise DispatchError(
                f"{ref.url} moved while it was being captured (head {head_sha[:10]}, fetched "
                f"{fetched[:10]}): open the review again"
            )
        git(dest, "checkout", "--quiet", "--detach", "FETCH_HEAD", timeout=FETCH_TIMEOUT)
    except GitError as exc:
        raise DispatchError(f"cannot fetch the source of {ref.url}: {exc}") from exc


def _mentions(source: Path, path: str) -> list[str] | None:
    """Files of ``source`` that mention the name of ``path``; None when the name says nothing."""
    stem = Path(path).stem
    if len(stem) < MIN_STEM_LENGTH or stem.lower() in GENERIC_STEMS:
        return None
    try:
        proc = subprocess.run(
            ["git", "grep", "-l", "-w", "-F", "-e", stem, "--", ".", f":!{path}"],
            cwd=source,
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode not in (0, 1):  # 1 means no match
        return None
    return proc.stdout.splitlines()


def references_markdown(source: Path, changed: list[str]) -> str:
    """Per changed file, the other files that mention its name: a starting point for the
    question "who consumes this", found by text search and therefore incomplete."""
    lines = [
        "# Files that mention each changed file",
        "",
        "Found by searching the file name as a whole word in the source at the head commit.",
        "A starting point only: dynamic references, build steps and other repositories are not here.",
        "",
    ]
    for path in changed[:MAX_REFERENCED_FILES]:
        hits = _mentions(source, path)
        lines.append(f"## {path}")
        if hits is None:
            lines.append("- not searched (name too short or too generic)")
        elif not hits:
            lines.append("- no other file mentions it")
        else:
            lines += [f"- {hit}" for hit in hits[:MAX_HITS_PER_FILE]]
            if len(hits) > MAX_HITS_PER_FILE:
                lines.append(f"- ... and {len(hits) - MAX_HITS_PER_FILE} more")
        lines.append("")
    if len(changed) > MAX_REFERENCED_FILES:
        lines.append(f"({len(changed) - MAX_REFERENCED_FILES} more changed files not searched)")
    return "\n".join(lines) + "\n"


def _changed_files(meta: JsonDict) -> list[str]:
    files = meta.get("files") or []
    return [str(item["path"]) for item in files if isinstance(item, dict) and item.get("path")]


def snapshot_pull_request(url: str, directory: Path) -> PullSnapshot:
    """Capture one pull request under ``directory`` (which must not exist yet)."""
    ref = parse_pr_url(url)
    meta = _gh_json("pr", "view", ref.url, "--json", META_FIELDS)
    head_sha = str(meta.get("headRefOid") or "")
    if not head_sha:
        raise DispatchError(f"GitHub did not return the head commit of {ref.url}")
    snapshot = PullSnapshot(
        ref=ref,
        title=str(meta.get("title") or ""),
        head_sha=head_sha,
        base_ref=str(meta.get("baseRefName") or ""),
        is_draft=bool(meta.get("isDraft")),
        directory=directory,
    )
    checkout_source(ref, head_sha, snapshot.source)
    atomic_write_text(snapshot.meta_file, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(snapshot.diff_file, _gh("pr", "diff", ref.url))
    atomic_write_text(
        snapshot.threads_file, json.dumps(open_threads(ref), indent=2, ensure_ascii=False) + "\n"
    )
    atomic_write_text(
        snapshot.references_file, references_markdown(snapshot.source, _changed_files(meta))
    )
    return snapshot


def current_head(ref: PullRef) -> str:
    """The head commit of the pull request now."""
    return str(_gh_json("pr", "view", ref.url, "--json", "headRefOid").get("headRefOid") or "")


def _after(stamp: str, since: datetime) -> bool:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) > since
    except ValueError:
        return False


def _authored(items: object, viewer: str, when_key: str, since: datetime) -> int:
    if not isinstance(items, list):
        return 0
    return sum(
        1
        for item in items
        if isinstance(item, dict)
        and str((item.get("author") or {}).get("login") or "") == viewer
        and _after(str(item.get(when_key) or ""), since)
    )


def activity_since(ref: PullRef, viewer: str, since: str, was_draft: bool) -> list[str]:
    """What ``viewer``'s account wrote on the pull request after ``since``, and a draft state
    change. A review round must write nothing, so anything listed here needs an explanation."""
    start = datetime.fromisoformat(since)
    state = _gh_json("pr", "view", ref.url, "--json", ACTIVITY_FIELDS)
    nodes, _ = _all_threads(ref)
    inline = sum(
        1
        for node in nodes
        for comment in _thread_comments(node)
        if comment["author"] == viewer and _after(comment["at"], start)
    )
    counts = (
        ("review(s)", _authored(state.get("reviews"), viewer, "submittedAt", start)),
        ("comment(s)", _authored(state.get("comments"), viewer, "createdAt", start)),
        ("inline comment(s)", inline),
    )
    found = [f"{count} {label} by {viewer}" for label, count in counts if count]
    if bool(state.get("isDraft")) != was_draft:
        found.append("draft state changed")
    return found
