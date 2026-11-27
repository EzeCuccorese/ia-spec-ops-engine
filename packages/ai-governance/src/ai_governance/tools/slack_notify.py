"""Allowlist-guarded Slack notifier using a local token and native Markdown blocks.

Posts directly to the Slack Web API (no third-party servers) using a bot (``xoxb-``) or
user (``xoxp-``) token read from an environment variable or macOS Keychain, and fails
closed unless the target matches an explicit allowlist. Defaults come from the ``[slack]``
config table; CLI flags override them. ``slack-notify replies`` reads a thread and
``slack-notify inbox`` polls a channel for new messages.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
SLACK_GET_UPLOAD_URL = "https://slack.com/api/files.getUploadURLExternal"
SLACK_COMPLETE_UPLOAD_URL = "https://slack.com/api/files.completeUploadExternal"
SLACK_REPLIES_URL = "https://slack.com/api/conversations.replies"
SLACK_HISTORY_URL = "https://slack.com/api/conversations.history"
CHANNEL_ID_RE = re.compile(r"^[A-Z0-9]{2,30}$")
DEFAULT_LOOKBACK_HOURS = 24
MAX_LOOKBACK_HOURS = 24 * 30
DEFAULT_TOKEN_ENV = "SLACK_BOT_TOKEN"
REPLIES_PAGE_LIMIT = 200
THREAD_TS_RE = re.compile(r"^\d{1,12}\.\d{1,9}$")


class SlackUploadError(RuntimeError):
    """A file upload step failed after Slack accepted the upload request."""


@dataclass(frozen=True)
class SlackConfig:
    """Defaults read from the ``[slack]`` config table (user layers only)."""

    channel: str = ""
    dm: str = ""
    allow: tuple[str, ...] = ()
    token_env: str = DEFAULT_TOKEN_ENV
    keychain_service: str = ""
    bot_name: str = ""


def load_config() -> SlackConfig:
    """Read ``slack.*`` settings; raises ``ConfigError`` on an invalid config file."""
    from ai_governance import settings

    values = settings.effective()

    def text(key: str) -> str:
        return str(values[key].value or "").strip()

    raw_allow = values["slack.allow"].value
    allow = tuple(str(item).strip() for item in (raw_allow or []) if str(item).strip())  # type: ignore[union-attr]
    return SlackConfig(
        channel=text("slack.channel"),
        dm=text("slack.dm"),
        allow=allow,
        token_env=text("slack.token_env") or DEFAULT_TOKEN_ENV,
        keychain_service=text("slack.keychain_service"),
        bot_name=text("slack.bot_name"),
    )


def resolve_channel(requested: str | None, config: SlackConfig) -> str:
    """Map ``None``/``default``/``dm`` to configured IDs; anything else is used as given."""
    if requested is None or requested == "default":
        channel, label = config.channel, "slack.channel"
    elif requested == "dm":
        channel, label = config.dm, "slack.dm"
    else:
        return requested.strip()
    if not channel:
        raise ValueError(f"no target given and {label} is not configured")
    return channel


@dataclass(frozen=True)
class SlackMessage:
    """Target channel, Markdown body, and optional thread timestamp."""

    channel: str
    markdown: str
    thread_ts: str | None = None


def fallback_text(markdown: str, limit: int = 3000) -> str:
    """Build a clean notification fallback from standard Markdown."""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", markdown)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    return text[:limit]


def resolve_token(token_env: str, keychain_service: str | None) -> str:
    token = os.environ.get(token_env, "").strip()
    if not token and keychain_service:
        try:
            proc = subprocess.run(
                ["security", "find-generic-password", "-s", keychain_service, "-w"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                token = proc.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            token = ""
    if not (token.startswith("xoxb-") or token.startswith("xoxp-")):
        raise RuntimeError(
            f"Missing Slack bot token (xoxb-/xoxp-) in ${token_env}"
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


def _decode_http_error(err: urllib.error.HTTPError) -> dict[str, Any] | None:
    try:
        with err:
            parsed = json.loads(err.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def post_markdown(
    token: str,
    message: SlackMessage,
    *,
    timeout: int = 15,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "channel": message.channel,
        "text": fallback_text(message.markdown),
        "blocks": [{"type": "markdown", "text": message.markdown}],
    }
    if message.thread_ts:
        payload["thread_ts"] = message.thread_ts

    req = urllib.request.Request(
        SLACK_POST_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if (err_payload := _decode_http_error(err)) is not None:
            return err_payload
        raise
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Unexpected Slack API response: {type(parsed).__name__}")
    return parsed


UPLOAD_TIMEOUT_SECONDS = 30


def _get_json(req: urllib.request.Request, timeout: int) -> object:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _slack_error_code(parsed: object) -> str:
    return parsed.get("error", "unknown") if isinstance(parsed, dict) else "invalid_response"


def _request_upload_url(
    token: str, filename: str, length: int, timeout: int
) -> tuple[dict[str, Any], tuple[str, str] | None]:
    """Step 1: returns (meta, None) when Slack refuses, else (meta, (upload_url, file_id))."""
    params = urllib.parse.urlencode({"filename": filename, "length": length})
    req = urllib.request.Request(
        f"{SLACK_GET_UPLOAD_URL}?{params}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        meta = _get_json(req, timeout)
    except urllib.error.HTTPError as err:
        if (err_payload := _decode_http_error(err)) is not None:
            return err_payload, None
        raise
    if not isinstance(meta, dict):
        return {"ok": False, "error": "invalid_upload_meta"}, None
    if not meta.get("ok"):
        return meta, None
    upload_url, file_id = meta.get("upload_url"), meta.get("file_id")
    if not (isinstance(upload_url, str) and upload_url.startswith("https://")):
        raise SlackUploadError("upload step 1 failed: invalid_upload_meta")
    if not (isinstance(file_id, str) and file_id):
        raise SlackUploadError("upload step 1 failed: invalid_upload_meta")
    return meta, (upload_url, file_id)


def _complete_upload(token: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Step 3: share the uploaded file; errors name only Slack's code, never the token."""
    req = urllib.request.Request(
        SLACK_COMPLETE_UPLOAD_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        parsed = _get_json(req, timeout)
    except urllib.error.HTTPError as err:
        code = (_decode_http_error(err) or {}).get("error") or f"http_{err.code}"
        raise SlackUploadError(f"upload step 3 failed: {code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        raise SlackUploadError(f"upload step 3 failed: {type(err).__name__}") from None
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        raise SlackUploadError(f"upload step 3 failed: {_slack_error_code(parsed)}")
    return parsed


def upload_file(
    token: str,
    channel: str,
    file_path: Path,
    comment: str | None = None,
    thread_ts: str | None = None,
) -> dict[str, Any]:
    """Upload a local file via Slack's modern external upload API."""
    raw = file_path.read_bytes()
    meta, target = _request_upload_url(token, file_path.name, len(raw), UPLOAD_TIMEOUT_SECONDS)
    if target is None:
        return meta
    upload_url, file_id = target
    _send_upload_bytes(upload_url, raw, timeout=UPLOAD_TIMEOUT_SECONDS)
    payload: dict[str, Any] = {
        "files": [{"id": file_id, "title": file_path.name}],
        "channel_id": channel,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if comment:
        payload["initial_comment"] = fallback_text(comment)
    return _complete_upload(token, payload, UPLOAD_TIMEOUT_SECONDS)


def _send_upload_bytes(upload_url: str, raw: bytes, *, timeout: int) -> None:
    """Step 2: POST the bytes to the presigned URL (it carries its own auth, no token)."""
    req = urllib.request.Request(
        upload_url,
        data=raw,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    # Error messages name only the status or exception type: the presigned URL is a secret.
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as err:
        raise SlackUploadError(f"upload step 2 failed: http_{err.code}") from None
    except (urllib.error.URLError, TimeoutError) as err:
        raise SlackUploadError(f"upload step 2 failed: {type(err).__name__}") from None
    if status >= 400:
        raise SlackUploadError(f"upload step 2 failed: http_{status}")


def _read_page(
    url: str, page_query: dict[str, str | int], token: str, label: str, timeout: int
) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(page_query)}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        parsed = _get_json(req, timeout)
    except urllib.error.HTTPError as err:
        payload = _decode_http_error(err) or {}
        raise RuntimeError(
            f"{label} failed: {payload.get('error') or f'http_{err.code}'}"
        ) from None
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        raise RuntimeError(f"{label} failed: {_slack_error_code(parsed)}")
    return parsed


def _next_cursor(parsed: dict[str, Any]) -> str:
    metadata = parsed.get("response_metadata")
    cursor = metadata.get("next_cursor", "") if isinstance(metadata, dict) else ""
    return cursor if parsed.get("has_more") and cursor else ""


def _read_pages(
    url: str, query: dict[str, str | int], token: str, label: str, *, timeout: int
) -> list[dict[str, Any]]:
    """GET a cursor-paginated Slack read method and collect its ``messages``."""
    messages: list[dict[str, Any]] = []
    cursor = ""
    while True:
        page_query = {
            **query,
            "limit": REPLIES_PAGE_LIMIT,
            **({"cursor": cursor} if cursor else {}),
        }
        parsed = _read_page(url, page_query, token, label, timeout)
        messages.extend(m for m in parsed.get("messages") or [] if isinstance(m, dict))
        cursor = _next_cursor(parsed)
        if not cursor:
            return messages


def fetch_replies(
    token: str, channel: str, thread_ts: str, *, oldest: str = "", timeout: int = 15
) -> list[dict[str, Any]]:
    """Read every message of a thread via ``conversations.replies`` (paginated)."""
    query: dict[str, str | int] = {"channel": channel, "ts": thread_ts}
    if oldest:
        query["oldest"] = oldest
    return _read_pages(SLACK_REPLIES_URL, query, token, "replies", timeout=timeout)


def fetch_history(
    token: str, channel: str, oldest: str, *, timeout: int = 15
) -> list[dict[str, Any]]:
    """Read channel messages newer than ``oldest`` via ``conversations.history``."""
    query: dict[str, str | int] = {"channel": channel, "oldest": oldest}
    return _read_pages(SLACK_HISTORY_URL, query, token, "history", timeout=timeout)


def _ts_value(ts: object) -> float:
    try:
        return float(str(ts))
    except ValueError:
        return 0.0


def _is_bot(message: dict[str, Any]) -> bool:
    return bool(message.get("bot_id")) or message.get("subtype") == "bot_message"


def _new_replies(
    token: str, channel: str, top: dict[str, Any], oldest: str, timeout: int
) -> dict[str, dict[str, Any]]:
    floor = _ts_value(oldest)
    ts = str(top.get("ts", ""))
    if not (top.get("reply_count") and _ts_value(top.get("latest_reply")) > floor):
        return {}
    return {
        str(reply.get("ts", "")): {**reply, "thread_ts": ts}
        for reply in fetch_replies(token, channel, ts, oldest=oldest, timeout=timeout)
        if str(reply.get("ts", "")) != ts and _ts_value(reply.get("ts", "")) > floor
    }


def collect_inbox(
    token: str, channel: str, oldest: str, *, timeout: int = 15
) -> tuple[list[dict[str, Any]], str]:
    """New top-level messages and thread replies after ``oldest``; returns (messages, max_ts).

    Each returned message carries ``thread_ts`` (its own ts for top-level messages).
    """
    floor = _ts_value(oldest)
    found: dict[str, dict[str, Any]] = {}
    for top in fetch_history(token, channel, oldest, timeout=timeout):
        ts = str(top.get("ts", ""))
        if _ts_value(ts) > floor:
            found[ts] = {**top, "thread_ts": top.get("thread_ts") or ts}
        found.update(_new_replies(token, channel, top, oldest, timeout))
    ordered = sorted(found.values(), key=lambda m: _ts_value(m.get("ts")))
    max_ts = str(ordered[-1]["ts"]) if ordered else oldest
    return ordered, max_ts


def inbox_record(channel: str, message: dict[str, Any]) -> dict[str, object]:
    """Project an inbox message to the fields printed by ``inbox``."""
    return {
        "channel": channel,
        "thread_ts": message.get("thread_ts", ""),
        "ts": message.get("ts", ""),
        "user": message.get("user") or message.get("bot_id") or "",
        "text": message.get("text", ""),
        "is_bot": _is_bot(message),
    }


def default_inbox_state(channel: str) -> Path:
    from ai_governance.paths import state_dir

    return state_dir() / "slack-inbox" / f"{channel}.json"


def read_inbox_state(path: Path) -> str:
    """Last seen ts from the state file; empty when the file does not exist yet."""
    if not path.is_file():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    last_ts = data.get("last_ts", "") if isinstance(data, dict) else ""
    if last_ts and not THREAD_TS_RE.match(str(last_ts)):
        raise ValueError(f"invalid last_ts in state file {path}")
    return str(last_ts)


def write_inbox_state(path: Path, last_ts: str) -> None:
    """Atomically replace the state file (write a sibling temp file, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps({"last_ts": last_ts}), encoding="utf-8")
    os.replace(tmp, path)


def reply_record(message: dict[str, Any]) -> dict[str, object]:
    """Project a Slack message to the fields printed by ``replies``."""
    return {
        "user": message.get("user") or message.get("bot_id") or "",
        "ts": message.get("ts", ""),
        "text": message.get("text", ""),
        "bot": bool(message.get("bot_id")) or message.get("subtype") == "bot_message",
    }


def _read_message(file_path: str | None, inline_text: str | None) -> str:
    if file_path == "-":
        return sys.stdin.read().strip()
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    if inline_text is not None:
        return inline_text.strip()
    raise ValueError("Provide either --file or --text.")


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--channel",
        help="Target channel/user ID, or 'default' / 'dm' to use [slack] channel / dm",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Allowed channel/user ID(s), comma-separated or repeatable; replaces [slack] allow "
        "(plus $SLACK_NOTIFY_ALLOW)",
    )
    parser.add_argument(
        "--token-env", help="Env var holding an xoxb/xoxp token ([slack] token_env)"
    )
    parser.add_argument(
        "--keychain-service",
        help="macOS Keychain service fallback when the token env var is unset",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance slack-notify",
        description="Send a Markdown message via a Slack token to an allowlisted target.",
    )
    _add_common_args(parser)
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--file", help="Path to Markdown file, or '-' for stdin")
    source.add_argument("--text", help="Inline Markdown text")
    parser.add_argument("--attach", type=Path, help="Optional local file path to upload and attach")
    parser.add_argument("--thread-ts", help="Optional parent message timestamp for thread replies")
    return parser


def _build_replies_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance slack-notify replies",
        description="Print a Slack thread as JSON lines (user, ts, text, bot).",
    )
    _add_common_args(parser)
    parser.add_argument("--thread-ts", required=True, help="Parent message timestamp")
    return parser


def _lookback_hours(raw: str) -> int:
    value = int(raw)
    if not 1 <= value <= MAX_LOOKBACK_HOURS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_LOOKBACK_HOURS}")
    return value


def _build_inbox_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance slack-notify inbox",
        description="Print new human messages (and thread replies) as JSON lines. "
        "Exit 0 when there are new messages, 1 when none, 2 on error.",
    )
    _add_common_args(parser)
    parser.add_argument("--state", type=Path, help="JSON state file with the last seen ts")
    parser.add_argument("--from", dest="from_user", help="Only messages from this user ID")
    parser.add_argument(
        "--lookback-hours",
        type=_lookback_hours,
        default=DEFAULT_LOOKBACK_HOURS,
        help="Window read on the first run, before a state file exists",
    )
    return parser


@dataclass(frozen=True)
class _Target:
    channel: str
    token_env: str
    keychain_service: str | None


def _resolve_target(args: argparse.Namespace) -> _Target:
    """Merge flags over config and enforce the allowlist; raises ValueError (fail closed)."""
    from ai_governance._config_core import ConfigError

    try:
        config = load_config()
    except ConfigError as exc:
        raise ValueError(str(exc)) from None
    channel = resolve_channel(args.channel, config)
    raw_allow = list(args.allow) if args.allow else list(config.allow)
    env_allow = os.environ.get("SLACK_NOTIFY_ALLOW", "")
    if env_allow:
        raw_allow.append(env_allow)
    allowed = parse_allowlist(raw_allow)
    if not allowed or channel not in allowed:
        raise ValueError(f"target '{channel}' is not in the configured allowlist.")
    return _Target(
        channel=channel,
        token_env=args.token_env or config.token_env,
        keychain_service=args.keychain_service or config.keychain_service or None,
    )


def _fail(message: str, code: int) -> int:
    print(f"slack-notify error: {message}", file=sys.stderr)
    return code


def replies_main(argv: list[str]) -> int:
    args = _build_replies_parser().parse_args(argv)
    if not THREAD_TS_RE.match(args.thread_ts):
        return _fail("--thread-ts must look like 1700000000.123456", 2)
    try:
        target = _resolve_target(args)
    except ValueError as exc:
        return _fail(str(exc), 2)
    try:
        token = resolve_token(target.token_env, target.keychain_service)
        messages = fetch_replies(token, target.channel, args.thread_ts)
    except (RuntimeError, OSError, ValueError) as exc:
        return _fail(str(exc), 1)
    for message in messages:
        print(json.dumps(reply_record(message), ensure_ascii=False))
    return 0


def _poll_inbox(args: argparse.Namespace, target: _Target) -> list[dict[str, Any]]:
    """Fetch new inbox messages and advance the saved cursor; raises on any failure."""
    if not CHANNEL_ID_RE.match(target.channel):
        raise ValueError("inbox needs a Slack channel ID such as C0123ABCD")
    state_path = args.state or default_inbox_state(target.channel)
    last_ts = read_inbox_state(state_path)
    oldest = last_ts or f"{time.time() - args.lookback_hours * 3600:.6f}"
    token = resolve_token(target.token_env, target.keychain_service)
    messages, max_ts = collect_inbox(token, target.channel, oldest)
    if max_ts not in (last_ts, oldest):
        write_inbox_state(state_path, max_ts)
    return messages


def _is_wanted(message: dict[str, Any], from_user: str | None) -> bool:
    return not _is_bot(message) and (not from_user or message.get("user") == from_user)


def inbox_main(argv: list[str]) -> int:
    try:
        args = _build_inbox_parser().parse_args(argv)
    except SystemExit as exc:  # argparse usage errors map to the documented error code
        return 0 if exc.code == 0 else 2
    try:
        target = _resolve_target(args)
        messages = _poll_inbox(args, target)
    except (RuntimeError, OSError, ValueError) as exc:
        return _fail(str(exc), 2)
    wanted = [m for m in messages if _is_wanted(m, args.from_user)]
    for message in wanted:
        print(json.dumps(inbox_record(target.channel, message), ensure_ascii=False))
    return 0 if wanted else 1


def _message_body(args: argparse.Namespace) -> str:
    """Read the markdown body; raises ValueError on a missing or empty message."""
    if not args.attach and not args.file and args.text is None:
        raise ValueError("provide --file, --text, or --attach.")
    markdown = ""
    if args.file or args.text is not None:
        try:
            markdown = _read_message(args.file, args.text)
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(str(exc)) from None
        if not markdown and not args.attach:
            raise ValueError("message content is empty.")
    return markdown


def _deliver(args: argparse.Namespace, target: _Target, markdown: str) -> dict[str, Any]:
    token = resolve_token(target.token_env, target.keychain_service)
    if args.attach:
        return upload_file(
            token, target.channel, args.attach, comment=markdown or None, thread_ts=args.thread_ts
        )
    return post_markdown(
        token, SlackMessage(channel=target.channel, markdown=markdown, thread_ts=args.thread_ts)
    )


def _print_result(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.attach:
        files = result.get("files") or []
        print(files[0].get("id", "ok") if files else "ok")
    else:
        print(result.get("ts", ""))


def notify_main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    try:
        target = _resolve_target(args)
        markdown = _message_body(args)
        if args.attach and not args.attach.is_file():
            raise ValueError(f"attachment not found: {args.attach}")
    except ValueError as exc:
        return _fail(str(exc), 2)
    try:
        result = _deliver(args, target, markdown)
    except (RuntimeError, OSError, ValueError) as exc:
        return _fail(str(exc), 1)
    if not result.get("ok"):
        return _fail(
            f"{result.get('error', 'unknown')} {result.get('response_metadata', '')}".strip(), 1
        )
    _print_result(args, result)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["replies"]:
        return replies_main(argv[1:])
    if argv[:1] == ["inbox"]:
        return inbox_main(argv[1:])
    return notify_main(argv)
