"""Draft release notes from a commit log with Gemini.

Writes the markdown body (no version heading) to ``--out``. On any failure it writes
nothing and exits 0, so the release falls back to the plain commit list.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-latest"

PROMPT = """You write release notes for a software project.
Use ONLY the commit subjects below. Do not invent changes.
Group them under these headings, omitting empty ones, in this order:
### Breaking changes
### Features
### Fixes
### Performance
Each item is one short sentence in {language}, starting with a capital letter.
Return markdown only, with no version heading and no preamble.

Commits:
{commits}
"""


def build_request(commits: str, language: str) -> dict[str, Any]:
    prompt = PROMPT.format(language=language, commits=commits)
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }


def extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    return "".join(str(part.get("text", "")) for part in parts).strip()


@dataclass(frozen=True)
class DraftOptions:
    language: str
    model: str
    api_key: str
    timeout: float


def draft(commits: str, options: DraftOptions) -> str:
    request = urllib.request.Request(
        API.format(model=options.model),
        data=json.dumps(build_request(commits, options.language)).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": options.api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=options.timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return extract_text(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commits", type=Path, required=True, help="commit subjects, one per line")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--language", default=os.environ.get("RELEASE_NOTES_LANGUAGE", "English"))
    parser.add_argument("--model", default=os.environ.get("RELEASE_NOTES_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("GEMINI_API_KEY not set: using the commit list instead")
        return 0
    try:
        options = DraftOptions(args.language, args.model, api_key, args.timeout)
        notes = draft(args.commits.read_text(encoding="utf-8"), options)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
        print(f"AI notes unavailable ({type(error).__name__}): using the commit list instead")
        return 0
    if not notes:
        print("AI notes empty: using the commit list instead")
        return 0
    args.out.write_text(notes + "\n", encoding="utf-8")
    print(f"wrote AI notes to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
