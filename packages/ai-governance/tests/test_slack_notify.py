"""Unit tests for the allowlist-guarded Slack notifier (ai-governance slack-notify)."""

from __future__ import annotations

import email.message
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest
from ai_governance.tools import slack_notify


def test_rejects_missing_or_unauthorized_allowlist(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SLACK_NOTIFY_ALLOW", raising=False)
    msg = tmp_path / "msg.md"
    msg.write_text("**[Test - Title]**", encoding="utf-8")

    # Missing allowlist fails closed
    assert slack_notify.main(["--channel", "C123", "--file", str(msg)]) == 2

    # Unauthorized channel rejected
    assert slack_notify.main(["--channel", "C999", "--allow", "C123,U456", "--file", str(msg)]) == 2


def test_posts_markdown_block_to_allowed_channel_and_prints_ts(monkeypatch, capsys) -> None:
    captured: dict = {}

    def fake_post(token: str, message: slack_notify.SlackMessage, *, timeout: int = 15) -> dict:
        captured.update(
            token=token,
            channel=message.channel,
            markdown=message.markdown,
            thread_ts=message.thread_ts,
            timeout=timeout,
        )
        return {"ok": True, "ts": "1700000000.123456"}

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-token")
    monkeypatch.setenv("SLACK_NOTIFY_ALLOW", "C123,U456")
    monkeypatch.setattr(slack_notify, "post_markdown", fake_post)

    rc = slack_notify.main(
        [
            "--channel",
            "C123",
            "--text",
            "**[Topic - Hello]**\n- Item [link](https://example.com)",
            "--thread-ts",
            "1700000000.000001",
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "1700000000.123456"
    assert captured["channel"] == "C123"
    assert captured["thread_ts"] == "1700000000.000001"
    assert slack_notify.fallback_text("**[Topic]** [x](https://a)") == "*[Topic]* x"


def test_resolve_token_keychain_and_error_paths(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr(
        slack_notify.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout="xoxb-keychain\n", stderr=""),
    )
    assert slack_notify.resolve_token("SLACK_BOT_TOKEN", "slack-svc") == "xoxb-keychain"

    monkeypatch.setattr(
        slack_notify.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no security")),
    )
    with pytest.raises(RuntimeError, match="Missing Slack bot token"):
        slack_notify.resolve_token("SLACK_BOT_TOKEN", "slack-svc")


def test_post_markdown_and_main_failure_branches(monkeypatch, tmp_path: Path) -> None:
    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"ok": True, "ts": "1.2"}).encode("utf-8")

    monkeypatch.setattr(slack_notify.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    out = slack_notify.post_markdown(
        "xoxb-1", slack_notify.SlackMessage(channel="C1", markdown="hi", thread_ts="0.9")
    )
    assert out["ok"] is True

    monkeypatch.setattr(slack_notify.sys, "stdin", io.StringIO("  from stdin  "))
    assert slack_notify._read_message("-", None) == "from stdin"
    with pytest.raises(ValueError, match="Provide either"):
        slack_notify._read_message(None, None)

    assert (
        slack_notify.main(["--channel", "C1", "--allow", "C1", "--file", str(tmp_path / "no.md")])
        == 2
    )
    assert slack_notify.main(["--channel", "C1", "--allow", "C1", "--text", "   "]) == 2

    monkeypatch.setenv("SLACK_BOT_TOKEN", "bad-token")
    assert slack_notify.main(["--channel", "C1", "--allow", "C1", "--text", "hi"]) == 1

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-ok")
    monkeypatch.setattr(
        slack_notify, "post_markdown", lambda *_a, **_k: {"ok": False, "error": "bad"}
    )
    assert slack_notify.main(["--channel", "C1", "--allow", "C1", "--text", "hi"]) == 1


def test_post_markdown_decodes_http_error_json(monkeypatch) -> None:
    err = urllib.error.HTTPError(
        slack_notify.SLACK_POST_URL,
        400,
        "Bad Request",
        email.message.Message(),
        io.BytesIO(b'{"ok": false, "error": "invalid_blocks"}'),
    )
    monkeypatch.setattr(
        slack_notify.urllib.request, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(err)
    )
    res = slack_notify.post_markdown("xoxb-1", slack_notify.SlackMessage("C1", "hi"))
    assert res["error"] == "invalid_blocks"

    bad_err = urllib.error.HTTPError(
        slack_notify.SLACK_POST_URL,
        502,
        "Bad Gateway",
        email.message.Message(),
        io.BytesIO(b"not-json"),
    )
    monkeypatch.setattr(
        slack_notify.urllib.request, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(bad_err)
    )
    with pytest.raises(urllib.error.HTTPError):
        slack_notify.post_markdown("xoxb-1", slack_notify.SlackMessage("C1", "hi"))
