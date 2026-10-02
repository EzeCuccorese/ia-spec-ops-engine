#!/usr/bin/env python3
"""
Custom in-house GitHub PR code review script using Gemini API.
Supports multi-language output, configurable file excludes, and explicit software engineering
principles (SOLID, Clean Code, Resource Management, Security, Concurrency).
"""

import fnmatch
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any


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


def call_gemini(prompt: str, api_key: str, model: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        raise RuntimeError(f"Gemini API call failed (HTTP {e.code}): {err_msg}") from e
    
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError(f"No candidates generated from Gemini: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise ValueError(f"No valid content parts generated from Gemini: {data}")
    return parts[0]["text"]


def _matches_any(filepath: str, patterns: list[str]) -> bool:
    name = os.path.basename(filepath)
    for p in patterns:
        p = p.strip()
        if not p:
            continue
        if fnmatch.fnmatch(filepath, p) or fnmatch.fnmatch(filepath, f"*/{p}") or fnmatch.fnmatch(name, p):
            return True
    return False


def get_pr_diff(exclude_patterns: list[str]) -> str:
    base_ref = os.environ.get("GITHUB_BASE_REF", "main")
    try:
        subprocess.run(
            ["git", "fetch", "origin", f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}"],
            check=False,
        )
        name_status = subprocess.check_output(
            ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
            text=True,
        ).splitlines()

        included_files = [f for f in name_status if not _matches_any(f, exclude_patterns)]
        if not included_files:
            return ""

        cmd = ["git", "diff", f"origin/{base_ref}...HEAD", "--"] + included_files
        return subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Error computing git diff against origin/{base_ref}: {e}", file=sys.stderr)
        return ""


def _validate_comment(c: Any) -> dict[str, Any] | None:
    if not isinstance(c, dict):
        return None
    path = c.get("path")
    line = c.get("line")
    body = c.get("body")
    if isinstance(line, str) and line.strip().isdigit():
        line = int(line.strip())
    if (
        isinstance(path, str)
        and isinstance(body, str)
        and isinstance(line, int)
        and not isinstance(line, bool)
        and line > 0
    ):
        return {"path": path, "line": line, "body": body}
    return None


def _filter_comments(comments: Any) -> list[dict[str, Any]]:
    if not isinstance(comments, list):
        return []
    valid = []
    for c in comments:
        v = _validate_comment(c)
        if v:
            valid.append(v)
    return valid


def _post_fallback(target: ReviewTarget, summary: Any, comments: list[dict[str, Any]]) -> None:
    url = f"https://api.github.com/repos/{target.owner}/{target.repo}/pulls/{target.pr_number}/reviews"
    clean_summary = (summary or "").strip() or "Review completed."
    fallback_body = f"## Gemini Code Review\n\n{clean_summary}"
    if comments:
        fallback_body += "\n\n### Detailed Comments\n"
        for c in comments:
            fallback_body += f"\n- **{c['path']}:{c['line']}**: {c['body']}"
    req = urllib.request.Request(
        url,
        data=json.dumps({"body": fallback_body, "event": "COMMENT"}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {target.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Posted fallback review: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"Failed to post fallback review: HTTP {e.code} - {e.read().decode('utf-8')}", file=sys.stderr)


def post_github_review(target: ReviewTarget, summary: Any, comments: list[dict[str, Any]]) -> None:
    valid_comments = _filter_comments(comments)
    url = f"https://api.github.com/repos/{target.owner}/{target.repo}/pulls/{target.pr_number}/reviews"
    
    clean_summary = (summary or "").strip() or "Review completed."
    payload: dict[str, Any] = {
        "body": clean_summary,
        "event": "COMMENT",
    }
    if valid_comments:
        commit_sha = os.environ.get("COMMIT_SHA")
        if not commit_sha:
            commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        payload["commit_id"] = commit_sha
        payload["comments"] = valid_comments

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {target.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Successfully posted inline review: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"Error posting review: {e.code} - {e.read().decode('utf-8')}", file=sys.stderr)
        _post_fallback(target, summary, valid_comments)


def _load_repo_instructions() -> str:
    for candidate in [".github/copilot-code-review-instructions.md", ".github/code-review-instructions.md"]:
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as f:
                return f.read()
    return ""


def build_prompt(diff: str, config: ReviewConfig, repo_instructions: str) -> str:
    return f"""
You are an expert, meticulous software engineer and code reviewer.
Review the pull request diff thoroughly across any language present (Python, TypeScript, JavaScript, Java, Go, etc.) as well as documentation/markdown (.md).
All review feedback and summaries MUST be written in {config.language}.

Engineering Principles & Standards to enforce:
- **SOLID Principles**:
  - S: Single Responsibility (avoid monolithic functions/classes with multiple concerns).
  - O: Open/Closed (prefer extensible design over modifying existing core modules).
  - L: Liskov Substitution (subtypes must be substitutable for base types without breaking behavior).
  - I: Interface Segregation (clients should not depend on interfaces they do not use).
  - D: Dependency Inversion (depend upon abstractions/interfaces, not concrete implementations).
- **Clean Code & Best Practices**:
  - Clear, domain-accurate naming; explicit typing; idiomatic language idioms.
  - Resource safety: ensure database pools, file handles, sockets, and network sessions are properly closed/disposed (e.g., using try/finally or async context managers).
  - Security & Concurrency: prevent SQL injection, path traversal, race conditions, unhandled exceptions.
{f"- Additional Standards: {config.standards}" if config.standards else ""}

Repository-specific guidelines:
{repo_instructions}

IMPORTANT INSTRUCTIONS FOR INLINE COMMENTS:
- Return a JSON object with this EXACT structure:
{{
  "summary": "High-level summary of changes, notable strengths, and overall architecture assessment.",
  "comments": [
    {{
      "path": "relative/file/path.ext",
      "line": 42,
      "body": "Actionable, specific feedback or proposed snippet for this line."
    }}
  ]
}}
- Only add inline comments on lines that were actually added or modified in the diff (marked with +).
- "line" MUST be the line number in the NEW version of the file.
- If there are no issues or suggestions on a specific line, do not create unnecessary comments.
- Do NOT flag dynamic model aliases like gemini-flash-latest as invalid.

Diff to review:
```diff
{diff}
```
"""


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
        print(f"Expected JSON object from Gemini response, got {type(data).__name__}", file=sys.stderr)
        return None
    return data


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    token = os.environ.get("GITHUB_TOKEN")
    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    pr_num = os.environ.get("PR_NUMBER")

    if not api_key:
        print("GEMINI_API_KEY missing. Skipping review.")
        return
    if not (token and repo_slug and pr_num):
        print("Missing GitHub context environment variables.", file=sys.stderr)
        sys.exit(1)

    config = _load_review_config()
    diff = get_pr_diff(config.exclude_patterns)
    if not diff.strip():
        print("Empty diff after excludes. Nothing to review.")
        return

    repo_instructions = _load_repo_instructions()
    prompt = build_prompt(diff, config, repo_instructions)

    owner, repo = repo_slug.split("/", 1)
    target = ReviewTarget(owner=owner, repo=repo, pr_number=pr_num, token=token)

    raw_response = call_gemini(prompt, api_key, config.model)
    review_data = _parse_review_response(raw_response)
    if review_data is None:
        _post_fallback(target, f"Review completed, but response was not a valid JSON object:\n\n{raw_response}", [])
        return

    post_github_review(target, review_data.get("summary", "Review completed."), review_data.get("comments", []))


if __name__ == "__main__":
    main()
