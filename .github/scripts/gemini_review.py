#!/usr/bin/env python3
"""
Custom in-house GitHub PR code review script using Gemini API.
Runs entirely in your own CI workflow without 3rd-party composite actions.
Submits an official PR review with inline comments on changed files (including .md).
"""

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


def call_gemini(prompt: str, api_key: str, model: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
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
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return text


def get_pr_diff() -> str:
    base_ref = os.environ.get("GITHUB_BASE_REF", "main")
    subprocess.run(["git", "fetch", "origin", base_ref], check=False)
    diff = subprocess.check_output(
        ["git", "diff", f"origin/{base_ref}...HEAD"],
        text=True,
    )
    return diff


def _filter_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for c in comments:
        path = c.get("path")
        line = c.get("line")
        body = c.get("body")
        if path and isinstance(line, int) and line > 0 and body:
            valid.append({"path": path, "line": line, "body": body})
    return valid


def _post_fallback(target: ReviewTarget, summary: str, comments: list[dict[str, Any]]) -> None:
    url = f"https://api.github.com/repos/{target.owner}/{target.repo}/issues/{target.pr_number}/comments"
    fallback_body = f"## Gemini Code Review\n\n{summary}\n\n### Inline Comments\n"
    for c in comments:
        fallback_body += f"\n- **{c['path']}:{c['line']}**: {c['body']}"
    req = urllib.request.Request(
        url,
        data=json.dumps({"body": fallback_body}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {target.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"Posted fallback comment: HTTP {resp.status}")


def post_github_review(target: ReviewTarget, summary: str, comments: list[dict[str, Any]]) -> None:
    valid_comments = _filter_comments(comments)
    url = f"https://api.github.com/repos/{target.owner}/{target.repo}/pulls/{target.pr_number}/reviews"
    payload = {
        "body": summary,
        "event": "COMMENT",
        "comments": valid_comments,
    }
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


def _load_instructions() -> str:
    inst_file = ".github/copilot-code-review-instructions.md"
    if os.path.exists(inst_file):
        with open(inst_file, encoding="utf-8") as f:
            return f.read()
    return ""


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    token = os.environ.get("GITHUB_TOKEN")
    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    pr_num = os.environ.get("PR_NUMBER")
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

    if not api_key:
        print("GEMINI_API_KEY missing. Skipping review.")
        return
    if not (token and repo_slug and pr_num):
        print("Missing GitHub context environment variables.", file=sys.stderr)
        sys.exit(1)

    diff = get_pr_diff()
    if not diff.strip():
        print("Empty diff. Nothing to review.")
        return

    instructions = _load_instructions()
    prompt = f"""
You are an expert, meticulous code reviewer.
Review the following pull request diff. Include review for documentation/markdown files (.md) as well as code files.
All output must be written in English.

Guidelines & Standards:
{instructions}

IMPORTANT INSTRUCTIONS FOR INLINE COMMENTS:
- Return a JSON object with this EXACT structure:
{{
  "summary": "High-level summary of the changes and overall quality assessment.",
  "comments": [
    {{
      "path": "relative/file/path.ext",
      "line": 42,
      "body": "Clear, concise feedback or suggestion for this specific line."
    }}
  ]
}}
- Only add inline comments on lines that were actually added or modified in the diff (marked with +).
- "line" must be the line number in the NEW version of the file.
- If there are no issues on a specific line, do not create unnecessary comments.
- Do NOT flag dynamic model aliases like gemini-flash-latest as invalid.

Diff to review:
```diff
{diff}
```
"""
    raw_response = call_gemini(prompt, api_key, model)
    review_data = json.loads(raw_response)
    owner, repo = repo_slug.split("/")
    target = ReviewTarget(owner=owner, repo=repo, pr_number=pr_num, token=token)
    post_github_review(target, review_data.get("summary", "Review completed."), review_data.get("comments", []))


if __name__ == "__main__":
    main()
