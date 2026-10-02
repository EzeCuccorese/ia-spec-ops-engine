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
from typing import Any


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
    # Fetch base if needed
    subprocess.run(["git", "fetch", "origin", base_ref], check=False)
    diff = subprocess.check_output(
        ["git", "diff", f"origin/{base_ref}...HEAD"],
        text=True,
    )
    return diff


def post_github_review(owner: str, repo: str, pr_number: str, token: str, summary: str, comments: list[dict[str, Any]]) -> None:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    
    # Filter comments to only valid paths and positive line numbers
    valid_comments = []
    for c in comments:
        path = c.get("path")
        line = c.get("line")
        body = c.get("body")
        if path and isinstance(line, int) and line > 0 and body:
            valid_comments.append({
                "path": path,
                "line": line,
                "body": body,
            })

    payload = {
        "body": summary,
        "event": "COMMENT",
        "comments": valid_comments,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Successfully posted review: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        print(f"Error posting inline review: {e.code} - {error_msg}", file=sys.stderr)
        # Fallback: post regular comment if line ranges were rejected
        fallback_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
        fallback_body = f"## Gemini Code Review\n\n{summary}\n\n### Inline Comments\n"
        for c in valid_comments:
            fallback_body += f"\n- **{c['path']}:{c['line']}**: {c['body']}"
        req_fb = urllib.request.Request(
            fallback_url,
            data=json.dumps({"body": fallback_body}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req_fb, timeout=30) as resp:
            print(f"Posted fallback summary comment: HTTP {resp.status}")


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN")
    github_repository = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

    if not api_key:
        print("GEMINI_API_KEY not provided. Skipping review.")
        return
    if not (github_token and github_repository and pr_number):
        print("Missing GitHub context environment variables.", file=sys.stderr)
        sys.exit(1)

    owner, repo = github_repository.split("/")

    diff = get_pr_diff()
    if not diff.strip():
        print("Empty diff. Nothing to review.")
        return

    instructions = ""
    inst_file = ".github/copilot-code-review-instructions.md"
    if os.path.exists(inst_file):
        with open(inst_file, "r", encoding="utf-8") as f:
            instructions = f.read()

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

    print(f"Calling Gemini ({model})...")
    raw_response = call_gemini(prompt, api_key, model)

    try:
        review_data = json.loads(raw_response)
    except Exception as e:
        print(f"Failed to parse JSON response from Gemini: {e}", file=sys.stderr)
        print(raw_response)
        sys.exit(1)

    summary = review_data.get("summary", "Review completed.")
    comments = review_data.get("comments", [])

    print(f"Submitting review to GitHub with {len(comments)} inline comments...")
    post_github_review(owner, repo, pr_number, github_token, summary, comments)


if __name__ == "__main__":
    main()
