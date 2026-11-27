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


def test_attach_uploads_file_and_prints_file_id(monkeypatch, tmp_path: Path, capsys) -> None:
    sample = tmp_path / "report.txt"
    sample.write_text("hello", encoding="utf-8")
    captured: dict = {}

    def fake_upload(
        token: str,
        channel: str,
        file_path: Path,
        comment: str | None = None,
        thread_ts: str | None = None,
    ) -> dict:
        captured.update(
            token=token,
            channel=channel,
            file_path=file_path,
            comment=comment,
            thread_ts=thread_ts,
        )
        return {"ok": True, "files": [{"id": "F012345"}]}

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-token")
    monkeypatch.setattr(slack_notify, "upload_file", fake_upload)

    rc = slack_notify.main(
        [
            "--channel",
            "C123",
            "--allow",
            "C123",
            "--attach",
            str(sample),
            "--text",
            "Attached report",
            "--thread-ts",
            "1700000000.000001",
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "F012345"
    assert captured["file_path"] == sample
    assert captured["comment"] == "Attached report"


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
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        slack_notify.post_markdown("xoxb-1", slack_notify.SlackMessage("C1", "hi"))
    assert exc_info.value.code == 502


class _JsonResp:
    def __init__(self, payload: object, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def __enter__(self) -> _JsonResp:
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _queue_urlopen(monkeypatch, responses: list) -> list:
    calls: list = []

    def fake(req, timeout: int = 0):
        calls.append((req, timeout))
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(slack_notify.urllib.request, "urlopen", fake)
    return calls


def _write_config(monkeypatch, tmp_path: Path, body: str) -> None:
    cfg_home = tmp_path / "xdg"
    (cfg_home / "ai-governance").mkdir(parents=True)
    (cfg_home / "ai-governance" / "config.toml").write_text(body, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_home))


def test_resolve_token_accepts_user_token(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-user-token")
    assert slack_notify.resolve_token("SLACK_USER_TOKEN", None) == "xoxp-user-token"


def test_upload_step2_failure_raises_without_token(monkeypatch, tmp_path: Path) -> None:
    sample = tmp_path / "a.txt"
    sample.write_text("x", encoding="utf-8")
    meta = {"ok": True, "upload_url": "https://files.example.com/up", "file_id": "F1"}
    err = urllib.error.HTTPError(
        "https://files.example.com/up", 500, "boom", email.message.Message(), io.BytesIO(b"")
    )
    _queue_urlopen(monkeypatch, [_JsonResp(meta), err])
    with pytest.raises(slack_notify.SlackUploadError, match="step 2 failed: http_500") as info:
        slack_notify.upload_file("xoxp-secret", "C0123ABCD", sample)
    assert "xoxp-secret" not in str(info.value)


def test_upload_step3_failure_keeps_slack_error_code(monkeypatch, tmp_path: Path) -> None:
    sample = tmp_path / "a.txt"
    sample.write_text("x", encoding="utf-8")
    meta = {"ok": True, "upload_url": "https://files.example.com/up", "file_id": "F1"}
    _queue_urlopen(
        monkeypatch,
        [_JsonResp(meta), _JsonResp({}), _JsonResp({"ok": False, "error": "not_in_channel"})],
    )
    with pytest.raises(slack_notify.SlackUploadError, match="step 3 failed: not_in_channel"):
        slack_notify.upload_file("xoxb-secret", "C0123ABCD", sample)


def test_upload_rejects_non_https_upload_url(monkeypatch, tmp_path: Path) -> None:
    sample = tmp_path / "a.txt"
    sample.write_text("x", encoding="utf-8")
    meta = {"ok": True, "upload_url": "http://files.example.com/up", "file_id": "F1"}
    _queue_urlopen(monkeypatch, [_JsonResp(meta)])
    with pytest.raises(slack_notify.SlackUploadError, match="invalid_upload_meta"):
        slack_notify.upload_file("xoxb-1", "C0123ABCD", sample)


def test_main_reports_upload_error_exit_1(monkeypatch, tmp_path: Path, capsys) -> None:
    sample = tmp_path / "a.txt"
    sample.write_text("x", encoding="utf-8")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")

    def boom(*_a, **_k):
        raise slack_notify.SlackUploadError("upload step 2 failed: http_500")

    monkeypatch.setattr(slack_notify, "upload_file", boom)
    rc = slack_notify.main(["--channel", "C1", "--allow", "C1", "--attach", str(sample)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "step 2 failed" in err and "xoxb-secret" not in err


def test_config_defaults_channel_alias_and_token_env(monkeypatch, tmp_path: Path, capsys) -> None:
    _write_config(
        monkeypatch,
        tmp_path,
        '[slack]\nchannel = "C0123ABCD"\ndm = "D0123ABCD"\n'
        'allow = ["C0123ABCD", "D0123ABCD"]\ntoken_env = "MY_SLACK_TOKEN"\n',
    )
    monkeypatch.delenv("SLACK_NOTIFY_ALLOW", raising=False)
    monkeypatch.setenv("MY_SLACK_TOKEN", "xoxp-from-config-env")
    sent: list = []
    monkeypatch.setattr(
        slack_notify,
        "post_markdown",
        lambda token, msg, **_k: sent.append((token, msg.channel)) or {"ok": True, "ts": "1.2"},
    )
    assert slack_notify.main(["--text", "hi"]) == 0
    assert slack_notify.main(["--channel", "dm", "--text", "hi"]) == 0
    assert slack_notify.main(["--channel", "default", "--text", "hi"]) == 0
    assert sent == [
        ("xoxp-from-config-env", "C0123ABCD"),
        ("xoxp-from-config-env", "D0123ABCD"),
        ("xoxp-from-config-env", "C0123ABCD"),
    ]
    # CLI --allow replaces the configured allowlist (still fail closed)
    assert slack_notify.main(["--channel", "dm", "--allow", "C0123ABCD", "--text", "hi"]) == 2
    assert "allowlist" in capsys.readouterr().err


def test_alias_without_config_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_NOTIFY_ALLOW", "C1")
    assert slack_notify.main(["--channel", "dm", "--text", "hi"]) == 2
    assert slack_notify.main(["--text", "hi"]) == 2


def test_replies_prints_json_lines_with_pagination(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-user")
    page1 = {
        "ok": True,
        "messages": [{"user": "U0123ABCD", "ts": "1.1", "text": "parent"}],
        "has_more": True,
        "response_metadata": {"next_cursor": "next"},
    }
    page2 = {
        "ok": True,
        "messages": [{"bot_id": "B0123ABCD", "ts": "1.2", "text": "bot reply"}],
        "has_more": False,
    }
    calls = _queue_urlopen(monkeypatch, [_JsonResp(page1), _JsonResp(page2)])
    rc = slack_notify.main(
        [
            "replies",
            "--channel",
            "C0123ABCD",
            "--allow",
            "C0123ABCD",
            "--thread-ts",
            "1700000000.000100",
            "--token-env",
            "SLACK_USER_TOKEN",
        ]
    )
    assert rc == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert lines == [
        {"user": "U0123ABCD", "ts": "1.1", "text": "parent", "bot": False},
        {"user": "B0123ABCD", "ts": "1.2", "text": "bot reply", "bot": True},
    ]
    assert "cursor=next" in calls[1][0].full_url
    assert all(timeout > 0 for _req, timeout in calls)


def test_replies_guards_and_api_error(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SLACK_NOTIFY_ALLOW", raising=False)
    base = ["replies", "--channel", "C0123ABCD", "--thread-ts", "1.2"]
    assert slack_notify.main(base) == 2  # no allowlist
    assert slack_notify.main([*base[:-1], "not-a-ts", "--allow", "C0123ABCD"]) == 2
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    _queue_urlopen(monkeypatch, [_JsonResp({"ok": False, "error": "thread_not_found"})])
    assert slack_notify.main([*base, "--allow", "C0123ABCD"]) == 1
    assert "thread_not_found" in capsys.readouterr().err


def _inbox_args(state: Path, *extra: str) -> list[str]:
    return [
        "inbox",
        "--channel",
        "C0123ABCD",
        "--allow",
        "C0123ABCD",
        "--state",
        str(state),
        *extra,
    ]


def test_inbox_prints_new_human_messages_and_updates_state(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxp-user")
    state = tmp_path / "state" / "inbox.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"last_ts": "100.000000"}), encoding="utf-8")
    history = {
        "ok": True,
        "messages": [
            {"user": "U0123ABCD", "ts": "105.0", "text": "top"},
            {"bot_id": "B0123ABCD", "ts": "104.0", "text": "bot"},
            {
                "user": "U0123ABCD",
                "ts": "90.0",
                "text": "old parent",
                "reply_count": 2,
                "latest_reply": "106.0",
            },
        ],
    }
    replies = {
        "ok": True,
        "messages": [
            {"user": "U0123ABCD", "ts": "90.0", "text": "old parent"},
            {"user": "U0999ZZZZ", "ts": "106.0", "text": "reply", "thread_ts": "90.0"},
        ],
    }
    calls = _queue_urlopen(monkeypatch, [_JsonResp(history), _JsonResp(replies)])
    assert slack_notify.main(_inbox_args(state)) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [(r["ts"], r["thread_ts"], r["is_bot"]) for r in lines] == [
        ("105.0", "105.0", False),
        ("106.0", "90.0", False),
    ]
    assert lines[0]["channel"] == "C0123ABCD"
    assert "oldest=100.000000" in calls[0][0].full_url
    assert all(req.full_url.startswith("https://slack.com/api/") for req, _t in calls)
    assert json.loads(state.read_text(encoding="utf-8")) == {"last_ts": "106.0"}


def test_inbox_from_filter_and_no_new_messages_exit_1(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    state = tmp_path / "inbox.json"
    state.write_text(json.dumps({"last_ts": "1.0"}), encoding="utf-8")
    page = {"ok": True, "messages": [{"user": "U0999ZZZZ", "ts": "5.0", "text": "x"}]}
    _queue_urlopen(monkeypatch, [_JsonResp(page)])
    assert slack_notify.main(_inbox_args(state, "--from", "U0123ABCD")) == 1
    assert capsys.readouterr().out == ""
    assert json.loads(state.read_text(encoding="utf-8")) == {"last_ts": "5.0"}

    _queue_urlopen(monkeypatch, [_JsonResp({"ok": True, "messages": []})])
    assert slack_notify.main(_inbox_args(state)) == 1


def test_inbox_errors_exit_2_and_keep_state(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.delenv("SLACK_NOTIFY_ALLOW", raising=False)
    state = tmp_path / "inbox.json"
    state.write_text(json.dumps({"last_ts": "1.0"}), encoding="utf-8")
    assert slack_notify.main(["inbox", "--channel", "C0123ABCD", "--state", str(state)]) == 2
    assert slack_notify.main(_inbox_args(state, "--lookback-hours", "0")) == 2
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
    _queue_urlopen(monkeypatch, [_JsonResp({"ok": False, "error": "channel_not_found"})])
    assert slack_notify.main(_inbox_args(state)) == 2
    err = capsys.readouterr().err
    assert "channel_not_found" in err and "xoxb-secret" not in err
    assert json.loads(state.read_text(encoding="utf-8")) == {"last_ts": "1.0"}


def test_inbox_default_state_path_is_under_state_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    path = slack_notify.default_inbox_state("C0123ABCD")
    assert path.parts[-2:] == ("slack-inbox", "C0123ABCD.json")
