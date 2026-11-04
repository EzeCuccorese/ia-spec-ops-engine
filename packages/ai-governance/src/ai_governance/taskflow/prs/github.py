"""The GitHub reader: the only module that starts ``gh``, and only to read.

* An allow-list admits ``auth status``, ``auth token`` and ``api graphql`` with a query that
  starts with ``query`` and holds no mutation. Nothing here can merge, approve or comment.
* Every ``gh`` child runs with ``GH_TOKEN``, ``GITHUB_TOKEN``, ``GH_ENTERPRISE_TOKEN`` and
  ``GH_HOST`` removed first; the chosen token is then set for that one child. The accounts are
  never switched (``gh auth switch`` does not exist here): the token of the account that can see
  the repository is read with ``gh auth token`` and kept in memory only.
* A failure is reported as one of a few fixed codes. ``gh`` stderr and stdout are inspected but
  never surfaced, so a token that leaked into them cannot reach a screen, a log or the cache.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .cache import PrCache
from .refs import PrRef, valid_repo
from .snapshot import (
    NO_ACCESS,
    NO_GH,
    RATE_LIMITED,
    TIMEOUT,
    UNEXPECTED,
    Parent,
    Snapshot,
    SyncError,
    ThreadExtra,
    dig,
    error_code,
    parent_from,
    parse,
    thread_nodes_ok,
)

TIMEOUT_S = 60
THREAD_PAGE = 100
MAX_THREAD_PAGES = 20
MERGEABLE_RETRY_S = 1.0
STRIPPED_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GH_HOST")
ALLOWED = frozenset({("auth", "status"), ("auth", "token"), ("api", "graphql")})
_AUTH_FLAGS = frozenset({"--json", "hosts", "--hostname", "github.com", "--no-refresh", "--user"})
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{8,255}")
_VARIABLE = re.compile(r"[a-z]+=")

PR_QUERY = """query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { name }
    pullRequest(number: $number) {
      state isDraft baseRefName headRefName mergeable reviewDecision title
      headRepository { nameWithOwner }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      reviewThreads(first: 100, after: $cursor) {
        totalCount pageInfo { hasNextPage endCursor } nodes { isResolved }
      }
    }
  }
}"""
PARENT_QUERY = """query($owner: String!, $name: String!, $base: String!, $qualified: String!) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $qualified) { name }
    pullRequests(headRefName: $base, states: [OPEN, MERGED, CLOSED], first: 10) {
      nodes { number state headRepository { nameWithOwner } }
      pageInfo { hasNextPage }
    }
  }
}"""


class GhFailure(Exception):
    """A read that could not complete; the message is always one of the fixed codes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Proc:
    code: int
    out: str
    err: str


def check_argv(argv: list[str]) -> None:
    """Refuse anything but the read-only calls this module is for (``ValueError``)."""
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        raise ValueError("gh argv must be a list of strings")
    if tuple(argv[:2]) not in ALLOWED:
        raise ValueError(f"gh {' '.join(argv[:2])} is not allowed: this reader is read-only")
    if argv[0] == "api":
        _check_api(argv[2:])
    else:
        _check_auth(argv[2:])


def _check_auth(rest: list[str]) -> None:
    for index, arg in enumerate(rest):
        after_user = index > 0 and rest[index - 1] == "--user"
        if arg not in _AUTH_FLAGS and not (after_user and _LOGIN.fullmatch(arg)):
            raise ValueError(f"unexpected gh auth argument {arg!r}")


def _check_api(rest: list[str]) -> None:
    pairs = [(rest[i], rest[i + 1]) for i in range(0, len(rest) - 1, 2)]
    if len(rest) % 2 or any(flag not in ("-f", "-F") for flag, _ in pairs):
        raise ValueError("gh api graphql takes only -f/-F variable pairs")
    _check_query([value for _, value in pairs if value.startswith("query=")])
    if not all(_VARIABLE.match(value) for _, value in pairs):
        raise ValueError("malformed gh variable")


def _check_query(queries: list[str]) -> None:
    if len(queries) != 1:
        raise ValueError("gh api graphql needs exactly one query")
    text = queries[0][len("query=") :]
    if not text.lstrip().startswith("query") or re.search(
        r"\b(mutation|subscription)\b", text, re.I
    ):
        raise ValueError("only read-only GraphQL queries are allowed")


class Gh:
    """Runs allow-listed ``gh`` calls with a clean credential environment."""

    def __init__(self, timeout: float = TIMEOUT_S) -> None:
        self.timeout = timeout

    def run(self, argv: list[str], token: str | None = None) -> Proc:
        check_argv(argv)
        if shutil.which("gh") is None:
            raise GhFailure(NO_GH)
        env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
        env.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1")
        if token:
            env["GH_TOKEN"] = token
        try:
            done = subprocess.run(  # noqa: S603 - argv list, allow-listed, no shell
                ["gh", *argv],
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GhFailure(TIMEOUT) from exc
        except OSError as exc:
            raise GhFailure(NO_GH) from exc
        return Proc(done.returncode, done.stdout or "", done.stderr or "")


def parse_logins(proc: Proc) -> list[tuple[str, bool]]:
    """(login, active) pairs from ``gh auth status --json hosts``; empty when unreadable."""
    try:
        hosts = json.loads(proc.out)["hosts"]["github.com"]
        return [(h["login"], bool(h.get("active"))) for h in hosts if _LOGIN.fullmatch(h["login"])]
    except (ValueError, KeyError, TypeError):
        return []


def parse_logins_text(text: str) -> list[tuple[str, bool]]:
    """The same from the plain ``gh auth status`` text (older gh versions)."""
    found: list[tuple[str, bool]] = []
    for chunk in text.split("Logged in to")[1:]:
        match = re.search(r"(?:account|as) ([A-Za-z0-9-]+)", chunk)
        if match:
            found.append((match.group(1), "Active account: true" in chunk))
    if found and not any(active for _, active in found):
        found[0] = (found[0][0], True)
    return found


class AccountBook:
    """Which logged-in account reads which owner, and the in-memory tokens to use them."""

    def __init__(self, gh: Gh, cache: PrCache | None = None) -> None:
        self.gh, self.cache = gh, cache
        self._logins: list[tuple[str, bool]] | None = None
        self._tokens: dict[str, str] = {}
        self._learned: dict[str, str] = {}

    def logins(self) -> list[tuple[str, bool]]:
        if self._logins is None:
            self._logins = self._discover()
        return self._logins

    def _discover(self) -> list[tuple[str, bool]]:
        try:
            found = parse_logins(self.gh.run(["auth", "status", "--json", "hosts"]))
            return found or parse_logins_text(self._plain_status())
        except GhFailure as failure:
            if failure.code == NO_GH:
                raise
            return []

    def _plain_status(self) -> str:
        proc = self.gh.run(["auth", "status"])
        return proc.out + proc.err

    def active(self) -> str | None:
        return next((login for login, is_active in self.logins() if is_active), None)

    def order(self, owner: str) -> list[str | None]:
        """Logins to try for ``owner``; None is the active account (no token needed)."""
        names, active = [login for login, _ in self.logins()], self.active()
        stored = (self.cache.accounts() if self.cache else {}).get(owner.lower())
        known = self._learned.get(owner.lower()) or stored

        def canonical(login: str | None) -> str:
            return next((n for n in names if login and n.lower() == login.lower()), "")

        preferred = [n for n in (canonical(known), canonical(owner)) if n]
        ranked: list[str | None] = []
        for item in [*preferred, "", *names]:
            slot = None if item in ("", active) else item
            if slot not in ranked:
                ranked.append(slot)
        return ranked

    def token(self, login: str) -> str | None:
        """The token of ``login`` (memoised in this process only), or None if unavailable."""
        if login in self._tokens:
            return self._tokens[login]
        proc = self.gh.run(
            ["auth", "token", "--hostname", "github.com", "--user", login, "--no-refresh"]
        )
        text = proc.out.strip()
        if proc.code != 0 or not _TOKEN.fullmatch(text):
            return None
        self._tokens[login] = text
        return text

    def learn(self, owner: str, login: str | None) -> None:
        """Remember (in memory and, as a non-secret mapping, on disk) who reads ``owner``."""
        login = login or self.active()
        if login and self._learned.get(owner.lower()) != login:
            self._learned[owner.lower()] = login
            if self.cache:
                self.cache.remember_account(owner, login)


def _json(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _interpret(proc: Proc) -> tuple[str, object]:
    """('ok', body) | ('rate'|'denied'|'bad', None) for one ``api graphql`` outcome."""
    body = _json(proc.out)
    if isinstance(body, dict) and body.get("errors"):
        code = error_code(body["errors"])
        if code == RATE_LIMITED:
            return "rate", None
        return ("denied", None) if code == NO_ACCESS else ("ok", body)
    if proc.code == 0:  # a success that is not a JSON object is a broken tool, not a denial
        return ("ok", body) if isinstance(body, dict) else ("bad", None)
    if "rate limit" in (proc.err + proc.out).lower():
        return "rate", None
    return "denied", None


class PrReader:
    """Reads a pull request and everything its status needs, with a bounded number of calls."""

    def __init__(
        self,
        gh: Gh | None = None,
        cache: PrCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.gh = gh or Gh()
        self.book = AccountBook(self.gh, cache)
        self.sleep = sleep

    # -- one graphql call, trying the accounts that may see the owner ---------------------
    def _graphql(self, owner: str, query: str, variables: list[str]) -> dict[str, Any]:
        for login in self.book.order(owner):
            token = None if login is None else self.book.token(login)
            if login is not None and token is None:
                continue
            proc = self.gh.run(["api", "graphql", "-f", f"query={query}", *variables], token)
            kind, body = _interpret(proc)
            if kind == "rate":
                raise GhFailure(RATE_LIMITED)
            if kind == "bad":
                raise GhFailure(UNEXPECTED)
            if kind == "ok" and isinstance(body, dict):
                self.book.learn(owner, login)
                return body
        raise GhFailure(NO_ACCESS)

    def _page(self, ref: PrRef, cursor: str | None) -> dict[str, Any]:
        owner, name = valid_repo(ref.repo).split("/")
        args = ["-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={ref.number}"]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        return self._graphql(owner, PR_QUERY, args)

    def _threads(self, ref: PrRef, first: dict[str, Any]) -> ThreadExtra:
        """Unresolved threads on the pages after ``first`` (at most ``MAX_THREAD_PAGES`` pages)."""
        block = _thread_block(first)
        if block is None:
            return ThreadExtra()
        found = 0
        for _ in range(MAX_THREAD_PAGES - 1):
            if block["pageInfo"].get("hasNextPage") is not True:
                return ThreadExtra(found, complete=True)
            block = self._next_block(ref, block["pageInfo"].get("endCursor"))
            if block is None:
                return ThreadExtra(found, complete=False)
            found += sum(1 for node in block["nodes"] if node["isResolved"] is False)
        return ThreadExtra(found, complete=block["pageInfo"].get("hasNextPage") is False)

    def _next_block(self, ref: PrRef, cursor: object) -> dict[str, Any] | None:
        if not isinstance(cursor, str) or not cursor:
            return None
        try:
            return _thread_block(self._page(ref, cursor))
        except GhFailure:
            return None

    def _parent(self, ref: PrRef, snapshot: Snapshot) -> Parent:
        owner, name = valid_repo(ref.repo).split("/")
        args = ["-f", f"owner={owner}", "-f", f"name={name}", "-f", f"base={snapshot.base}"]
        args += ["-f", f"qualified=refs/heads/{snapshot.base}"]
        try:
            return parent_from(self._graphql(owner, PARENT_QUERY, args), ref.repo)
        except GhFailure:
            return Parent("unknown")

    def _first_page(self, ref: PrRef) -> tuple[dict[str, Any], Snapshot | SyncError]:
        response = self._page(ref, None)
        result = parse(response)
        if (
            isinstance(result, Snapshot)
            and result.state == "OPEN"
            and result.mergeable == "unknown"
        ):
            self.sleep(MERGEABLE_RETRY_S)
            retried = self._retry_page(ref)
            if retried is not None:
                response, result = retried
        return response, result

    def _retry_page(self, ref: PrRef) -> tuple[dict[str, Any], Snapshot | SyncError] | None:
        """A second read while GitHub computes ``mergeable``; None keeps the first answer
        (mergeable stays unknown, never invented)."""
        try:
            response = self._page(ref, None)
        except GhFailure:
            return None
        return response, parse(response)

    def fetch(self, ref: PrRef) -> Snapshot | SyncError:
        """The validated snapshot of ``ref``, or the fixed-code error. Never raises."""
        try:
            response, first = self._first_page(ref)
            if isinstance(first, SyncError):
                return first
            result = parse(response, self._threads(ref, response))
            if not isinstance(result, Snapshot):
                return result
            if result.state == "OPEN" and result.base != result.default_branch:
                result = result.with_parent(self._parent(ref, result))
            return result
        except GhFailure as failure:
            return SyncError(failure.code)
        except (ValueError, KeyError, TypeError):
            return SyncError(UNEXPECTED)


def _thread_block(response: object) -> dict[str, Any] | None:
    """The ``reviewThreads`` block of a page, or None when it is not the expected shape."""
    block = dig(response, "data", "repository", "pullRequest", "reviewThreads")
    if not isinstance(block, dict) or not isinstance(block.get("pageInfo"), dict):
        return None
    return block if thread_nodes_ok(block.get("nodes")) else None
