#!/usr/bin/env python3
"""Custom in-house GitHub PR code review script using the Gemini API.

Supports full PR reviews on initial open/reopen/label triggers, incremental
commit-range reviews on subsequent pushes (CodeRabbit style), pre-annotated diff
line numbers, structured JSON responses, and priority-ordered diff budgeting.
"""

from __future__ import annotations

import fnmatch
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

MAX_DIFF_CHARS = 80_000
GEMINI_TIMEOUT = 180
MAX_RETRIES = 2
SNAP_TOLERANCE = 3
TRUNCATION_NOTICE = "\n... [diff truncated for review budget] ...\n"
REVIEW_MARKER_PREFIX = "<!-- gemini-review-sha:"
REVIEW_SHA_RE = re.compile(r"<!--\s*gemini-review-sha:\s*([0-9a-f]{7,40})\s*-->")
HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
HEX_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
LINE_TOKEN_RE = re.compile(r"^\+?L?(\d+)$")

_RETRYABLE_NETWORK_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    http.client.IncompleteRead,
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "comments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "line": {"type": "INTEGER"},
                    "severity": {"type": "STRING", "enum": ["P1", "P2", "P3"]},
                    "body": {"type": "STRING"},
                },
                "required": ["path", "line", "body"],
            },
        },
    },
    "required": ["summary", "comments"],
}


@dataclass
class ReviewTarget:
    owner: str
    repo: str
    pr_number: str
    token: str


@dataclass
class ReviewConfig:
    language: str
    exclude_patterns: list[str]
    standards: str
    model: str


@dataclass(frozen=True)
class ReviewEvent:
    base_ref: str
    head_sha: str
    action: str = ""
    before_sha: str = ""


@dataclass(frozen=True)
class ReviewMetadata:
    mode: str = "full"
    commit_sha: str = ""
    out_of_hunk: tuple[dict[str, Any], ...] = ()


@dataclass
class _DiffCursor:
    path: str = ""
    new_line: int | None = None
    in_header: bool = True


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def _request_gemini(url: str, body: bytes, api_key: str) -> dict[str, Any]:
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Gemini API call failed (HTTP {e.code}): {err_msg}") from e
        except _RETRYABLE_NETWORK_ERRORS as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Gemini API connection failed: {e}") from e
    raise RuntimeError("Gemini API call failed after retries")


def call_gemini(prompt: str, api_key: str, model: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }
    data = _request_gemini(url, json.dumps(payload).encode("utf-8"), api_key)
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError(f"No candidates generated from Gemini: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise ValueError(f"No valid content parts generated from Gemini: {data}")
    return parts[0]["text"]


def _matches_any(filepath: str, patterns: list[str]) -> bool:
    name = os.path.basename(filepath)
    for raw in patterns:
        pattern = raw.strip()
        if not pattern:
            continue
        if (
            fnmatch.fnmatch(filepath, pattern)
            or fnmatch.fnmatch(filepath, f"*/{pattern}")
            or fnmatch.fnmatch(name, pattern)
        ):
            return True
    return False


def _file_priority(filepath: str) -> tuple[int, str]:
    normalized = filepath.replace("\\", "/").removeprefix("./")
    parts = normalized.split("/")
    name = parts[-1]
    is_test = (
        "tests" in parts
        or "evals" in parts
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js"))
    )
    if normalized.endswith(".md"):
        return (3, normalized)
    if is_test:
        return (2, normalized)
    if "src" in parts or normalized.startswith(
        ("scripts/", ".github/scripts/", ".github/workflows/")
    ):
        return (0, normalized)
    return (1, normalized)


def _is_gemini_bot_review(review: dict[str, Any], body_text: str) -> bool:
    user = review.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    return login == "github-actions[bot]" or "Gemini Code Review" in body_text


def _extract_review_sha(review: Any) -> str | None:
    if not isinstance(review, dict):
        return None
    raw_body = review.get("body")
    body_text = raw_body if isinstance(raw_body, str) else ""
    match = REVIEW_SHA_RE.search(body_text)
    if match:
        return match.group(1)
    commit_id = review.get("commit_id")
    if isinstance(commit_id, str) and _is_gemini_bot_review(review, body_text):
        stripped = commit_id.strip()
        if HEX_SHA_RE.fullmatch(stripped):
            return stripped
    return None


def fetch_last_reviewed_sha(target: ReviewTarget) -> str | None:
    url = (
        f"https://api.github.com/repos/{target.owner}/{target.repo}"
        f"/pulls/{target.pr_number}/reviews?per_page=100"
    )
    req = urllib.request.Request(url, headers=_github_headers(target.token))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            reviews = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, *_RETRYABLE_NETWORK_ERRORS, ValueError) as err:
        print(f"Could not fetch prior reviews ({type(err).__name__}): {err}", file=sys.stderr)
        return None
    if not isinstance(reviews, list):
        return None
    for review in reversed(reviews):
        sha = _extract_review_sha(review)
        if sha:
            return sha
    return None


def _is_valid_ancestor(ancestor_sha: str, head_sha: str = "HEAD") -> bool:
    if not ancestor_sha or not HEX_SHA_RE.fullmatch(ancestor_sha):
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, head_sha],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _same_commit(last_sha: str, head_sha: str) -> bool:
    return last_sha == head_sha or (len(last_sha) >= 7 and head_sha.startswith(last_sha))


def _can_diff_before(last_sha: str | None, event: ReviewEvent) -> bool:
    return bool(
        event.action == "synchronize"
        and last_sha
        and event.before_sha
        and event.before_sha != "0" * 40
        and _is_valid_ancestor(event.before_sha, "HEAD")
    )


def resolve_review_scope(target: ReviewTarget, event: ReviewEvent) -> tuple[str, str]:
    full_range = f"origin/{event.base_ref}...HEAD"
    if event.action == "labeled":
        return ("full", full_range)

    last_sha = fetch_last_reviewed_sha(target)
    if last_sha and _same_commit(last_sha, event.head_sha):
        return ("skip", "")
    if last_sha and _is_valid_ancestor(last_sha, "HEAD"):
        return ("incremental", f"{last_sha}..HEAD")
    if _can_diff_before(last_sha, event):
        return ("incremental", f"{event.before_sha}..HEAD")
    return ("full", full_range)


def get_pr_diff(exclude_patterns: list[str], diff_range: str | None = None) -> str:
    base_ref = os.environ.get("GITHUB_BASE_REF", "main")
    target_range = diff_range or f"origin/{base_ref}...HEAD"
    try:
        subprocess.run(
            ["git", "fetch", "origin", f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}"],
            check=False,
        )
        name_status = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", target_range],
            text=True,
        ).splitlines()

        included_files = sorted(
            (f for f in name_status if not _matches_any(f, exclude_patterns)),
            key=_file_priority,
        )
        if not included_files:
            return ""

        cmd = ["git", "diff", "--unified=3", target_range, "--", *included_files]
        return subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Error computing git diff for {target_range}: {e}", file=sys.stderr)
        return ""


def _annotate_diff_line(
    line: str,
    cursor: _DiffCursor,
    valid_lines: dict[str, set[int]],
) -> str:
    if line.startswith("diff --git ") or line.startswith("--- a/") or line == "--- /dev/null":
        cursor.in_header = True
        cursor.new_line = None
        return line
    if cursor.in_header and line.startswith("+++ b/"):
        cursor.path = line[6:].strip()
        return line
    if cursor.in_header and line == "+++ /dev/null":
        cursor.path = ""
        return line
    hunk = HUNK_HEADER_RE.match(line)
    if hunk:
        cursor.in_header = False
        cursor.new_line = int(hunk.group(1))
        return line
    return _annotate_hunk_line(line, cursor, valid_lines)


def _annotate_hunk_line(
    line: str,
    cursor: _DiffCursor,
    valid_lines: dict[str, set[int]],
) -> str:
    if cursor.new_line is None:
        return line
    if line.startswith("+"):
        line_no = cursor.new_line
        if cursor.path:
            valid_lines.setdefault(cursor.path, set()).add(line_no)
        cursor.new_line += 1
        return f"+L{line_no}: {line[1:]}"
    if line.startswith(" "):
        line_no = cursor.new_line
        cursor.new_line += 1
        return f" L{line_no}: {line[1:]}"
    if line.startswith("-"):
        return f"-      {line[1:]}"
    return line


def annotate_diff(
    raw_diff: str,
    max_chars: int = MAX_DIFF_CHARS,
) -> tuple[str, dict[str, set[int]]]:
    if not raw_diff:
        return "", {}
    cursor = _DiffCursor()
    valid_lines: dict[str, set[int]] = {}
    emitted: list[str] = []
    total_chars = 0
    budget = max(0, max_chars - len(TRUNCATION_NOTICE))
    truncated = False

    for raw_line in raw_diff.splitlines():
        pending: dict[str, set[int]] = {}
        annotated = _annotate_diff_line(raw_line, cursor, pending)
        added_len = len(annotated) + (1 if emitted else 0)
        if total_chars + added_len > max_chars or (budget > 0 and total_chars + added_len > budget):
            truncated = True
            break
        for path, numbers in pending.items():
            valid_lines.setdefault(path, set()).update(numbers)
        emitted.append(annotated)
        total_chars += added_len

    result = "\n".join(emitted)
    if truncated:
        if max_chars < len(TRUNCATION_NOTICE):
            return raw_diff[:max_chars], valid_lines
        return result + TRUNCATION_NOTICE, valid_lines
    return result, valid_lines


def _parse_line_number(raw_line: Any) -> int | None:
    if isinstance(raw_line, bool):
        return None
    if isinstance(raw_line, int):
        return raw_line if raw_line > 0 else None
    if isinstance(raw_line, str):
        match = LINE_TOKEN_RE.match(raw_line.strip())
        if match:
            value = int(match.group(1))
            return value if value > 0 else None
    return None


def _validate_comment(comment: Any) -> dict[str, Any] | None:
    if not isinstance(comment, dict):
        return None
    path = comment.get("path")
    body = comment.get("body")
    line = _parse_line_number(comment.get("line"))
    if not (isinstance(path, str) and path.strip() and isinstance(body, str) and body.strip()):
        return None
    if line is None:
        return None

    clean_body = body.strip()
    severity = comment.get("severity")
    if isinstance(severity, str):
        tag = severity.strip().upper()
        if tag in {"P1", "P2", "P3"} and not clean_body.startswith(("**[P", "[P")):
            clean_body = f"**[{tag}]** {clean_body}"

    return {"path": path.strip(), "line": line, "body": clean_body}


def _filter_comments(comments: Any) -> list[dict[str, Any]]:
    if not isinstance(comments, list):
        return []
    valid: list[dict[str, Any]] = []
    for comment in comments:
        validated = _validate_comment(comment)
        if validated is not None:
            valid.append(validated)
    return valid


def _snap_comment(
    comment: dict[str, Any],
    valid_lines: dict[str, set[int]],
) -> tuple[dict[str, Any], bool]:
    path_lines = valid_lines.get(comment["path"])
    if not path_lines:
        return comment, False
    line = comment["line"]
    if line in path_lines:
        return comment, True
    candidates = [cand for cand in path_lines if abs(cand - line) <= SNAP_TOLERANCE]
    if not candidates:
        return comment, False
    nearest = min(candidates, key=lambda cand: (abs(cand - line), cand))
    return {**comment, "line": nearest}, True


def snap_comments_to_diff(
    comments: list[dict[str, Any]],
    valid_lines: dict[str, set[int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not valid_lines:
        return comments, []
    inline: list[dict[str, Any]] = []
    out_of_hunk: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for comment in comments:
        snapped, is_inline = _snap_comment(comment, valid_lines)
        if not is_inline:
            out_of_hunk.append(comment)
            continue
        key = (snapped["path"], snapped["line"], snapped["body"])
        if key not in seen:
            seen.add(key)
            inline.append(snapped)
    return inline, out_of_hunk


def _resolve_commit_sha(explicit_sha: str = "") -> str:
    candidate = (explicit_sha or os.environ.get("COMMIT_SHA", "")).strip()
    if candidate:
        return candidate
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def _format_review_body(
    summary: Any,
    comments: list[dict[str, Any]],
    meta: ReviewMetadata,
    include_comments: bool,
) -> str:
    heading = (
        "## Gemini Code Review (Incremental)"
        if meta.mode == "incremental"
        else "## Gemini Code Review"
    )
    clean_summary = (str(summary).strip() if summary is not None else "") or "Review completed."
    sections = [heading, clean_summary]

    if include_comments and comments:
        lines = ["### Detailed Comments", ""]
        lines.extend(f"- **{c['path']}:{c['line']}**: {c['body']}" for c in comments)
        sections.append("\n".join(lines))

    if meta.out_of_hunk:
        lines = ["### Notes Outside Diff Hunks", ""]
        lines.extend(f"- **{c['path']}:{c['line']}**: {c['body']}" for c in meta.out_of_hunk)
        sections.append("\n".join(lines))

    if meta.commit_sha:
        sections.append(f"{REVIEW_MARKER_PREFIX} {meta.commit_sha} -->")

    return "\n\n".join(sections)


def _post_fallback(
    target: ReviewTarget,
    summary: Any,
    comments: list[dict[str, Any]],
    meta: ReviewMetadata | None = None,
) -> None:
    url = f"https://api.github.com/repos/{target.owner}/{target.repo}/pulls/{target.pr_number}/reviews"
    resolved_meta = meta or ReviewMetadata()
    body = _format_review_body(summary, comments, resolved_meta, include_comments=True)
    req = urllib.request.Request(
        url,
        data=json.dumps({"body": body, "event": "COMMENT"}).encode("utf-8"),
        headers=_github_headers(target.token),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Posted fallback review: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(
            f"Failed to post fallback review: HTTP {e.code} - {e.read().decode('utf-8')}",
            file=sys.stderr,
        )


def post_github_review(
    target: ReviewTarget,
    summary: Any,
    comments: list[dict[str, Any]],
    meta: ReviewMetadata | None = None,
) -> None:
    valid_comments = _filter_comments(comments)
    base_meta = meta or ReviewMetadata()
    commit_sha = _resolve_commit_sha(base_meta.commit_sha)
    final_meta = ReviewMetadata(
        mode=base_meta.mode,
        commit_sha=commit_sha,
        out_of_hunk=base_meta.out_of_hunk,
    )
    body = _format_review_body(summary, [], final_meta, include_comments=False)
    payload: dict[str, Any] = {"body": body, "event": "COMMENT"}
    if valid_comments and commit_sha:
        payload["commit_id"] = commit_sha
        payload["comments"] = valid_comments

    url = f"https://api.github.com/repos/{target.owner}/{target.repo}/pulls/{target.pr_number}/reviews"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_github_headers(target.token),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Successfully posted inline review: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"Error posting review: {e.code} - {e.read().decode('utf-8')}", file=sys.stderr)
        _post_fallback(target, summary, valid_comments, final_meta)


def _load_repo_instructions() -> str:
    for candidate in (
        ".github/copilot-code-review-instructions.md",
        ".github/code-review-instructions.md",
        ".engine_tools/.github/copilot-code-review-instructions.md",
    ):
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as handle:
                return handle.read()
    return ""


_PROMPT_TEMPLATE = """You are a demanding, adversarial senior code reviewer.
Review this diff across all languages (Python, TypeScript/JS, YAML/Actions, shell, Markdown).
Write all summaries and comments in {language}.
Review Scope: {scope_desc}

Strict Review Rules:
- Zero filler praise (never write "great job", "notable strengths", or generic compliments).
- Skip style/formatting/import nits already handled by linters and formatters.
- Focus by severity:
  - P1: real bugs, broken API/type contracts, security flaws (injection, path traversal, secrets or request bodies in logs, ReDoS/nested-repetition regexes), race conditions, resource leaks, fail-open security guards.
  - P2: unhandled timeouts/network failures, bare exception swallowing, missing validation (`NaN`, `Infinity`, overflow, upstream shapes), weak tests asserting bare exception types or mocking the unit under test.
  - P3: concrete local simplifications or harmful duplication with direct maintenance impact.
- Enforce engineering fundamentals: SOLID, Clean Code, Resource Safety.
{standards_line}
Repository Guidelines:
{repo_instructions}

Pre-Annotated Diff & Output Format:
- Lines starting with `+L<num>:` are added/modified lines whose NEW-file line number is `<num>`.
- Lines starting with ` L<num>:` are context lines; lines starting with `-      ` are deletions.
- For every finding, set `"line"` to the exact integer `<num>` from a `+L<num>:` line, `"path"` to the relative file path, and `"severity"` to `"P1"`, `"P2"`, or `"P3"`.
- Include a concise ```suggestion block when proposing a direct line replacement.
- If there are no actionable issues, return `"comments": []` and a factual 1-2 sentence summary.
- Do NOT flag dynamic model aliases such as `gemini-flash-latest`.

Diff to review:
```diff
{diff}
```
"""


def build_prompt(
    diff: str,
    config: ReviewConfig,
    repo_instructions: str,
    scope: tuple[str, str] = ("full", ""),
) -> str:
    mode, diff_range = scope
    scope_desc = (
        f"Incremental Commit Review (commits `{diff_range}` since the last review). "
        "Review ONLY defects introduced or exposed by these new changes."
        if mode == "incremental"
        else "Full PR Review (all changes against the base branch)."
    )
    standards_line = f"- Additional Standards: {config.standards}\n" if config.standards else ""
    return _PROMPT_TEMPLATE.format(
        language=config.language,
        scope_desc=scope_desc,
        standards_line=standards_line,
        repo_instructions=repo_instructions,
        diff=diff,
    )


def _load_review_config() -> ReviewConfig:
    raw_excludes = os.environ.get("EXCLUDE_PATTERNS", "*.lock,package-lock.json")
    return ReviewConfig(
        language=os.environ.get("REVIEW_LANGUAGE", "English"),
        exclude_patterns=[p.strip() for p in raw_excludes.split(",") if p.strip()],
        standards=os.environ.get("REVIEW_STANDARDS", "SOLID, Clean Code, Resource Safety"),
        model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
    )


def _parse_review_response(raw_response: str) -> dict[str, Any] | None:
    cleaned = raw_response.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start : end + 1]
    elif cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as err:
        print(f"Failed to parse Gemini response as JSON: {err}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(
            f"Expected JSON object from Gemini response, got {type(data).__name__}", file=sys.stderr
        )
        return None
    return data


def _require_github_context() -> tuple[str, ReviewTarget] | None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("GEMINI_API_KEY missing. Skipping review.")
        return None
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo_slug = os.environ.get("GITHUB_REPOSITORY", "").strip()
    pr_num = os.environ.get("PR_NUMBER", "").strip()
    if not (token and repo_slug and pr_num) or "/" not in repo_slug:
        print("Missing GitHub context environment variables.", file=sys.stderr)
        sys.exit(1)
    owner, repo = repo_slug.split("/", 1)
    return api_key, ReviewTarget(owner=owner, repo=repo, pr_number=pr_num, token=token)


def _submit_review_response(
    target: ReviewTarget,
    raw_response: str,
    valid_lines: dict[str, set[int]],
    meta_seed: ReviewMetadata,
) -> None:
    review_data = _parse_review_response(raw_response)
    if review_data is None:
        _post_fallback(
            target,
            f"Review completed, but response was not a valid JSON object:\n\n{raw_response}",
            [],
            meta_seed,
        )
        return

    validated = _filter_comments(review_data.get("comments", []))
    inline, out_of_hunk = snap_comments_to_diff(validated, valid_lines)
    meta = ReviewMetadata(
        mode=meta_seed.mode,
        commit_sha=meta_seed.commit_sha,
        out_of_hunk=tuple(out_of_hunk),
    )
    post_github_review(target, review_data.get("summary", "Review completed."), inline, meta)


def main() -> None:
    ctx = _require_github_context()
    if ctx is None:
        return
    api_key, target = ctx
    config = _load_review_config()
    head_sha = _resolve_commit_sha()
    event = ReviewEvent(
        base_ref=os.environ.get("GITHUB_BASE_REF", "main"),
        head_sha=head_sha,
        action=os.environ.get("GITHUB_EVENT_ACTION", ""),
        before_sha=os.environ.get("BEFORE_SHA", ""),
    )
    mode, diff_range = resolve_review_scope(target, event)
    if mode == "skip":
        print(f"Commit {head_sha} already reviewed. Skipping.")
        return

    raw_diff = get_pr_diff(config.exclude_patterns, diff_range)
    if not raw_diff.strip():
        print("Empty diff after excludes. Nothing to review.")
        return

    annotated_diff, valid_lines = annotate_diff(raw_diff, MAX_DIFF_CHARS)
    prompt = build_prompt(annotated_diff, config, _load_repo_instructions(), (mode, diff_range))
    try:
        raw_response = call_gemini(prompt, api_key, config.model)
    except (RuntimeError, *_RETRYABLE_NETWORK_ERRORS, ValueError) as err:
        print(
            f"Gemini review unavailable ({type(err).__name__}: {err}). Skipping.", file=sys.stderr
        )
        return

    _submit_review_response(
        target, raw_response, valid_lines, ReviewMetadata(mode=mode, commit_sha=head_sha)
    )


if __name__ == "__main__":
    main()
