"""Unit tests for the allowlist-guarded Slack notifier (ai-governance slack-notify)."""

from __future__ import annotations

from pathlib import Path

from ai_governance.tools import slack_notify


def test_rejects_missing_or_unauthorized_allowlist(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SLACK_NOTIFY_ALLOW", raising=False)
    msg = tmp_path / "msg.md"
    msg.write_text("**[Test - Title]**", encoding="utf-8")

    # Missing allowlist fails closed
    assert slack_notify.main(["--channel", "C123", "--file", str(msg)]) == 2

    # Unauthorized channel rejected
    assert slack_notify.main(["--channel", "C999", "--allow", "C123,U456", "--file", str(msg)]) == 2


def test_posts_markdown_block_to_allowed_channel_and_prints_ts(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    captured: dict = {}

    def fake_post(token: str, channel: str, markdown: str, thread_ts: str | None = None) -> dict:
        captured.update(
            token=token, channel=channel, markdown=markdown, thread_ts=thread_ts
        )
        return {"ok": True, "ts": "1700000000.123456"}

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-token")
    monkeypatch.setattr(slack_notify, "post_markdown", fake_post)

    rc = slack_notify.main(
        [
            "--channel",
            "C123",
            "--allow",
            "C123,U456",
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
