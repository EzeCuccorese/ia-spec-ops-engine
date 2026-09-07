"""
Tests unitarios para las herramientas Jira y Confluence (ai_governance.tools).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_governance.tools import confluence, jira


def test_jira_check_env_missing(monkeypatch):
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("ATLASSIAN_URL", raising=False)

    with pytest.raises(SystemExit):
        jira.check_env()


def test_confluence_check_env_missing(monkeypatch):
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("ATLASSIAN_URL", raising=False)

    with pytest.raises(SystemExit):
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
    adf = jira._md_to_adf(text)
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


def test_confluence_md_to_storage():
    md = "# Heading 1\n\nSome paragraph\n\n```python\nprint('hi')\n```"
    storage = confluence.md_to_storage(md)
    assert "<h1>Heading 1</h1>" in storage
    assert "<p>Some paragraph</p>" in storage
    assert "<pre><code>" in storage


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
def test_atlassian_urlerror_handling(mock_urlopen, monkeypatch, capsys):
    import urllib.error

    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

    with pytest.raises(SystemExit):
        jira.get("/issue/FAIL-1")
    err = capsys.readouterr().err
    assert "Network error" in err

    with pytest.raises(SystemExit):
        confluence.get("/content/FAIL-1")
    err = capsys.readouterr().err
    assert "Network error" in err
