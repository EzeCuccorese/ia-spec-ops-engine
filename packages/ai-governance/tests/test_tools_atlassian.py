"""
Tests unitarios para las herramientas Jira y Confluence (ai_governance.tools).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from ai_governance.tools import confluence, jira


def _without_credentials(monkeypatch, tmp_path):
    """No Atlassian credentials anywhere: env, profiles file, or the values the module
    captured from the developer's environment at import time."""

    for name in ("ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "ATLASSIAN_URL", "ATLASSIAN_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ATLASSIAN_PROFILES_FILE", raising=False)
    monkeypatch.setenv("AI_GOVERNANCE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))


def test_jira_check_env_missing(monkeypatch, tmp_path):
    from ai_governance.tools.atlassian_common import AtlassianConfigError

    _without_credentials(monkeypatch, tmp_path)

    with pytest.raises(AtlassianConfigError, match="ATLASSIAN_EMAIL"):
        jira.check_env()


def test_confluence_check_env_missing(monkeypatch, tmp_path):
    from ai_governance.tools.atlassian_common import AtlassianConfigError

    _without_credentials(monkeypatch, tmp_path)

    with pytest.raises(AtlassianConfigError, match="ATLASSIAN_EMAIL"):
        confluence.check_env()


def test_jira_adf_to_md():
    node = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "Hello ", "marks": []},
            {"type": "text", "text": "World", "marks": [{"type": "strong"}]},
        ],
    }
    md = jira._adf_to_md(node)
    assert md.strip() == "Hello **World**"


def test_jira_md_to_adf():
    text = "- Item 1\n- Item 2"
    adf = jira.md_to_adf(text)
    assert adf["type"] == "doc"
    assert len(adf["content"]) == 1
    assert adf["content"][0]["type"] == "bulletList"


@patch("urllib.request.urlopen")
def test_jira_cmd_issue(mock_urlopen, monkeypatch, capsys):
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"fields": {"summary": "Bug in checkout", "status": {"name": "Open"}, "issuetype": {"name": "Bug"}}}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    jira.cmd_issue("PROJ-123")
    captured = capsys.readouterr().out
    assert "[PROJ-123] Bug in checkout" in captured
    assert "**Status**: Open" in captured


def test_confluence_html_to_md():
    html = "<h1>Title</h1><p>This is <strong>bold</strong> and <code>code</code></p>"
    md = confluence.html_to_md(html)
    assert "# Title" in md
    assert "**bold**" in md
    assert "`code`" in md


_CODE_MACRO_HTML = (
    '<p>Diagram:</p><ac:structured-macro ac:name="code" ac:schema-version="1">'
    '<ac:parameter ac:name="language">bash</ac:parameter>'
    "<ac:plain-text-body><![CDATA[a <b> & c\n  └─ d]]></ac:plain-text-body>"
    "</ac:structured-macro><p>after</p>"
)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (_CODE_MACRO_HTML, ["```bash\na <b> & c\n  └─ d\n```", "Diagram:", "after"]),
        (
            _CODE_MACRO_HTML.replace('"', "'"),
            ["```bash\na <b> & c\n  └─ d\n```", "Diagram:", "after"],
        ),
        (
            "<ol><li><p>first</p></li><li><p>second <code>x</code></p></li></ol>"
            "<ul><li><p>dot</p></li></ul>",
            ["1. first\n2. second `x`", "- dot"],
        ),
        ("<blockquote><p>Draft note</p></blockquote>", ["> Draft note"]),
    ],
    ids=["code-macro", "code-macro-single-quotes", "ordered-list", "quote"],
)
def test_confluence_html_to_md_keeps_structure(html, expected):
    md = confluence.html_to_md(html)
    for fragment in expected:
        assert fragment in md


def test_confluence_md_to_storage():
    md = "# Heading 1\n\nSome paragraph\n\n```python\nprint('hi')\n```"
    storage = confluence.md_to_storage(md)
    assert "<h1>Heading 1</h1>" in storage
    assert "<p>Some paragraph</p>" in storage


@patch("urllib.request.urlopen")
def test_confluence_cmd_read(mock_urlopen, monkeypatch, capsys):
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"title": "Architecture Doc", "body": {"storage": {"value": "<p>Hello Confluence</p>"}}, "space": {"key": "ARCH"}}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    confluence.cmd_read("12345")
    captured = capsys.readouterr().out
    assert "# Architecture Doc" in captured
    assert "Hello Confluence" in captured


@patch("urllib.request.urlopen")
def test_atlassian_urlopen_timeout(mock_urlopen, monkeypatch):
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"{}"
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    jira.get("/issue/TEST-1")
    assert mock_urlopen.call_args.kwargs.get("timeout") == 30.0

    confluence.get("/content/123")
    assert mock_urlopen.call_args.kwargs.get("timeout") == 30.0


def test_confluence_escape_cql_literal():
    raw = 'hello "world" \\ test'
    escaped = confluence.escape_cql_literal(raw)
    assert escaped == r"hello \"world\" \\ test"

    # Plain string remains unchanged
    assert confluence.escape_cql_literal("simple query") == "simple query"


@patch("urllib.request.urlopen")
def test_confluence_cmd_search_pagination(mock_urlopen, monkeypatch, capsys):
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    mock_resp = MagicMock()
    # 2 results returned out of 10 total
    mock_resp.read.return_value = (
        b'{"results": [{"id": "1", "title": "Doc 1", "space": {"key": "ENG"}}, '
        b'{"id": "2", "title": "Doc 2", "space": {"key": "ENG"}}], '
        b'"size": 2, "totalSize": 10}'
    )
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    confluence.cmd_search('architecture "spec" \\ 1', space_key="ENG")
    captured = capsys.readouterr().out
    assert "Results for" in captured
    assert "More results exist (2 of 10 shown)" in captured


@patch("urllib.request.urlopen")
def test_atlassian_urlerror_handling(mock_urlopen, monkeypatch):
    import urllib.error

    from ai_governance.tools.atlassian_common import AtlassianRequestError

    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

    with pytest.raises(AtlassianRequestError, match="Network error"):
        jira.get("/issue/FAIL-1")

    with pytest.raises(AtlassianRequestError, match="Network error"):
        confluence.get("/content/FAIL-1")


def test_unknown_profile_raises_with_known_list(monkeypatch, tmp_path):
    from ai_governance.tools import atlassian_common

    _without_credentials(monkeypatch, tmp_path)
    (tmp_path / "atlassian.json").write_text('{"work": {"email": "a", "token": "b", "url": "u"}}')
    with pytest.raises(atlassian_common.UnknownProfileError) as err:
        atlassian_common.load_profile_config("nope")
    assert "nope" in str(err.value) and "work" in str(err.value) and "default" in str(err.value)
    assert atlassian_common.load_profile_config("work")["email"] == "a"


def test_timeout_is_read_at_call_time(monkeypatch):
    from ai_governance.tools import atlassian_common

    monkeypatch.setenv("ATLASSIAN_TIMEOUT", "7.5")
    assert atlassian_common.atlassian_timeout() == 7.5
    monkeypatch.setenv("ATLASSIAN_TIMEOUT", "junk")
    assert atlassian_common.atlassian_timeout() == 30.0


def test_legacy_profiles_file_is_still_read(monkeypatch, tmp_path):
    from ai_governance.tools import atlassian_common

    _without_credentials(monkeypatch, tmp_path)
    legacy = tmp_path / ".config" / "atlassian"
    legacy.mkdir(parents=True)
    (legacy / "profiles.json").write_text('{"old": {"email": "o", "token": "t", "url": "u/"}}')
    assert atlassian_common.load_profile_config("old") == {"email": "o", "token": "t", "url": "u"}


def test_check_env_unknown_profile_raises_config_error(monkeypatch, tmp_path):
    from ai_governance.tools import atlassian_common

    _without_credentials(monkeypatch, tmp_path)
    monkeypatch.setenv("ATLASSIAN_PROFILE", "missing-prof")
    with pytest.raises(atlassian_common.AtlassianConfigError, match="missing-prof"):
        atlassian_common.check_env()


def test_cli_entrypoints_catch_atlassian_errors(monkeypatch, tmp_path, capsys):
    _without_credentials(monkeypatch, tmp_path)
    assert jira.main(["issue", "PROJ-1"]) == 1
    assert "Missing required environment variables" in capsys.readouterr().err

    assert confluence.main(["read", "12345"]) == 1
    assert "Missing required environment variables" in capsys.readouterr().err


@patch("urllib.request.urlopen")
def test_cli_entrypoints_catch_request_errors(mock_urlopen, monkeypatch, capsys):
    import urllib.error

    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")
    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

    assert jira.main(["issue", "FAIL-1"]) == 1
    assert "Network error" in capsys.readouterr().err

    assert confluence.main(["read", "12345"]) == 1
    assert "Network error" in capsys.readouterr().err


@patch("urllib.request.urlopen")
def test_execute_request_http_error_replaces_non_utf8_bytes(mock_urlopen, monkeypatch):
    import email.message
    import io
    import urllib.error

    from ai_governance.tools import atlassian_common

    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")
    mock_urlopen.side_effect = urllib.error.HTTPError(
        "https://company.atlassian.net/rest/api/3/issue/BAD-1",
        502,
        "Bad Gateway",
        email.message.Message(),
        io.BytesIO(b"\xff\xfe gateway error"),
    )

    with pytest.raises(atlassian_common.AtlassianRequestError, match="HTTP 502 Error"):
        atlassian_common.execute_request(
            "GET", "https://company.atlassian.net/rest/api/3/issue/BAD-1"
        )
