"""
pre_check.py — Proactive PreToolUse heuristic checker.
Warns agents when executing blatantly wasteful terminal commands without blocking execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

LOCKFILES = (
    "package-lock.json",
    "yarn.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "poetry.lock",
    "composer.lock",
    "uv.lock",
)

PATTERNS = (
    (
        "lockfile",
        lambda c: any(
            re.search(rf"\b(cat|less|more|bat)\b.*\b{re.escape(lf)}\b", c) for lf in LOCKFILES
        ),
        "This lockfile may contain thousands of lines. Frugal alternative: "
        "use `rg '\"package\":' <file>` or package-specific dependency inspection tools.",
    ),
    (
        "curl_without_jq",
        lambda c: bool(re.search(r"\bcurl\b", c) and "jq" not in c and re.search(r"https?://", c)),
        "This API call may return a large payload. Append `| jq -r '...'` "
        "with the minimal projection needed.",
    ),
    (
        "git_log_without_limit",
        lambda c: bool(
            re.search(r"\bgit\s+log\b", c) and not re.search(r"(-n\s*\d+|--oneline|-\d+\b)", c)
        ),
        "`git log` without limits may print the entire history. Use `git log --oneline -n 10`.",
    ),
    (
        "find_root",
        lambda c: bool(re.search(r"\bfind\s+/(?:\s|$)", c) and "-maxdepth" not in c),
        "`find /` without `-maxdepth` may traverse the entire filesystem. Add `-maxdepth N`.",
    ),
    (
        "logs_without_tail",
        lambda c: bool(
            re.search(r"\b(docker|kubectl)\s+logs\b", c) and "--tail" not in c and "-n" not in c
        ),
        "Log streams can be huge. Append `--tail 100`.",
    ),
    (
        "build_without_filter",
        lambda c: bool(
            re.search(r"\b(npm|yarn|pnpm)\s+(run\s+)?build\b", c)
            and "tail" not in c
            and "--silent" not in c
        ),
        "Consider constraining build output: append `2>&1 | tail -40` or the runner's silent flag.",
    ),
)


def _token_regex(token: str) -> str:
    """Build a regex fragment for one whitespace-delimited token of a `replaces` entry."""
    if token.startswith("<") and token.endswith(">"):
        return r"\S+"
    return re.escape(token)


def _entry_regex(entry: str) -> str:
    """Turn a `replaces` entry (with `<placeholder>` tokens) into a bounded regex."""
    tokens = entry.split()
    body = r"\s+".join(_token_regex(tok) for tok in tokens)
    return rf"\b{body}\b" if tokens and tokens[0][0].isalnum() else body


def _build_matcher(entry: str) -> Callable[[str], bool] | None:
    """Compile a `replaces` catalog entry into a command matcher.

    Most entries describe a literal command shape (e.g. ``git worktree add
    <path>``) and become a straightforward regex. Entries that describe a
    missing flag (e.g. ``docker logs without --tail``) become a positive
    match on the base command plus a negative check that the flag is absent.
    """
    negative = re.match(r"^(?P<base>.+?)\bwithout\s+(?P<flag>\S+)\s*$", entry)
    if negative:
        base_pattern = re.compile(_entry_regex(negative.group("base").strip()), re.IGNORECASE)
        flag = negative.group("flag")

        def matcher(command: str, _base: re.Pattern[str] = base_pattern, _flag: str = flag) -> bool:
            return bool(_base.search(command)) and _flag not in command

        return matcher

    pattern = re.compile(_entry_regex(entry), re.IGNORECASE)

    def positive_matcher(command: str, _pattern: re.Pattern[str] = pattern) -> bool:
        return bool(_pattern.search(command))

    return positive_matcher


# (id, deterministic command, purpose, manual commands it replaces)
REPLACEMENTS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "progress-here",
        "ai-governance progress here",
        "resume the task bound to this repository/branch",
        ("cat PROGRESS.md", "git log to reconstruct task state"),
    ),
    (
        "ws-worktree",
        "ws worktree <repo> <target> <branch>",
        "create an isolated worktree with workspace conventions",
        ("git worktree add <path>",),
    ),
    ("ws-hooks", "ws hooks status", "inspect the quality gate", ("cat .git/hooks/*",)),
    (
        "ws-detect",
        "ws detect --json",
        "detect the repository stacks",
        ("which java node python go",),
    ),
    (
        "jira-issue",
        "ai-governance jira issue <KEY>",
        "read Jira issues as compact Markdown",
        ("curl <atlassian>/rest/api",),
    ),
    (
        "confluence-read",
        "ai-governance confluence read <page>",
        "read Confluence pages as compact Markdown",
        ("curl <atlassian>/wiki/rest/api",),
    ),
    (
        "claude-usage",
        "ai-governance telemetry claude-usage",
        "estimate Claude spend from local transcripts",
        ("grep/parse ~/.claude/projects/**/*.jsonl",),
    ),
)


def replacement_patterns() -> tuple[tuple[str, Callable[[str], bool], str], ...]:
    """Advice pointing the agent at deterministic tools that replace manual commands."""
    patterns: list[tuple[str, Callable[[str], bool], str]] = []
    for tool_id, command, purpose, replaces in REPLACEMENTS:
        for index, entry in enumerate(replaces):
            matcher = _build_matcher(entry)
            if matcher is not None:
                advice = f"Deterministic alternative: `{command}` — {purpose}."
                patterns.append((f"tool:{tool_id}:{index}", matcher, advice))
    return tuple(patterns)


class PreCheck:
    @staticmethod
    def check_command(
        command: str,
        session_id: str | None = None,
        runtime_dir: Path | None = None,
        extra_patterns: Sequence[tuple[str, Callable[[str], bool], str]] = (),
    ) -> str | None:
        if not command or "#nofrugal" in command or os.environ.get("FRUGAL") == "0":
            return None

        warned: set[str] = set()
        warnings_file = None
        if runtime_dir and session_id:
            safe_session = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:24]
            warnings_file = runtime_dir / "sessions" / f"{safe_session}.json"
            if warnings_file.exists():
                try:
                    warned = set(json.loads(warnings_file.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError):
                    warned = set()

        for pid, matcher, advice in (*PATTERNS, *extra_patterns):
            if pid in warned:
                continue
            if matcher(command):
                if warnings_file:
                    try:
                        warnings_file.parent.mkdir(parents=True, exist_ok=True)
                        warned.add(pid)
                        temporary: Path | None = None
                        try:
                            with tempfile.NamedTemporaryFile(
                                mode="w",
                                encoding="utf-8",
                                dir=warnings_file.parent,
                                delete=False,
                            ) as handle:
                                json.dump(sorted(warned), handle)
                                handle.flush()
                                os.fsync(handle.fileno())
                                temporary = Path(handle.name)
                            temporary.replace(warnings_file)
                        finally:
                            if temporary and temporary.exists():
                                temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                return advice
        return None
