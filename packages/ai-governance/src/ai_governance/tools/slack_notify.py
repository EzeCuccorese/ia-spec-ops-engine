"""Allowlist-guarded Slack notifier using a local Bot Token and native Markdown blocks.

Posts directly to ``https://slack.com/api/chat.postMessage`` (no third-party servers)
using a Slack Bot Token (``xoxb-...``) read from an environment variable or macOS Keychain,
and fails closed unless ``--channel`` matches an explicit allowlist.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"


def fallback_text(markdown: str, limit: int = 3000) -> str:
    """Build a clean notification fallback from standard Markdown."""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", markdown)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    return text[:limit]


def resolve_token(token_env: str, keychain_service: str | None) -> str:
    token = os.environ.get(token_env, "").strip()
    if not token and keychain_service:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", keychain_service, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            token = proc.stdout.strip()
    if not token.startswith("xoxb-"):
        raise RuntimeError(
            f"Missing Slack bot token (xoxb-...) in ${token_env}"
            + (f" or keychain service '{keychain_service}'" if keychain_service else "")
        )
    return token


def parse_allowlist(raw_values: list[str]) -> set[str]:
    allowed: set[str] = set()
    for raw in raw_values:
        for item in raw.split(","):
            cleaned = item.strip()
            if cleaned:
                allowed.add(cleaned)
    return allowed


def post_markdown(
    token: str,
    channel: str,
    markdown: str,
    thread_ts: str | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "channel": channel,
        "text": fallback_text(markdown),
        "blocks": [{"type": "markdown", "text": markdown}],
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    req = urllib.request.Request(
        SLACK_POST_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _read_message(file_path: str | None, inline_text: str | None) -> str:
    if file_path == "-":
        return sys.stdin.read().strip()
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    if inline_text is not None:
        return inline_text.strip()
    raise ValueError("Provide either --file or --text.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance slack-notify",
        description="Send a Markdown message via a Slack Bot Token to an allowlisted target.",
    )
    parser.add_argument("--channel", required=True, help="Target Slack channel or user ID")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Allowed channel/user ID(s), comma-separated or repeatable (else $SLACK_NOTIFY_ALLOW)",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="Path to Markdown file, or '-' for stdin")
    source.add_argument("--text", help="Inline Markdown text")
    parser.add_argument("--thread-ts", help="Optional parent message timestamp for thread replies")
    parser.add_argument("--token-env", default="SLACK_BOT_TOKEN", help="Env var holding xoxb token")
    parser.add_argument(
        "--keychain-service",
        help="Optional macOS Keychain service name fallback when token env var is unset",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    raw_allow = list(args.allow)
    env_allow = os.environ.get("SLACK_NOTIFY_ALLOW", "")
    if env_allow:
        raw_allow.append(env_allow)
    allowed = parse_allowlist(raw_allow)
    if not allowed or args.channel not in allowed:
        print(
            f"slack-notify error: target '{args.channel}' is not in the configured allowlist.",
            file=sys.stderr,
        )
        return 2

    try:
        markdown = _read_message(args.file, args.text)
    except Exception as exc:
        print(f"slack-notify error: {exc}", file=sys.stderr)
        return 2

    if not markdown:
        print("slack-notify error: message content is empty.", file=sys.stderr)
        return 2

    try:
        token = resolve_token(args.token_env, args.keychain_service)
        result = post_markdown(token, args.channel, markdown, thread_ts=args.thread_ts)
    except Exception as exc:
        print(f"slack-notify error: {exc}", file=sys.stderr)
        return 1

    if not result.get("ok"):
        print(
            f"slack-notify error: {result.get('error', 'unknown')} "
            f"{result.get('response_metadata', '')}".strip(),
            file=sys.stderr,
        )
        return 1

    print(result["ts"])
    return 0
