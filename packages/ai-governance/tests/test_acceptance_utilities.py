"""
test_acceptance_utilities.py — Acceptance tests for utilities contracts U06–U10.

Contracts from 02-CONTRATOS-DE-TEST.md:
- U06 (test_atlassian_profiles_and_pagination): Search in Jira and Confluence supports pagination
      and multiple configuration profiles cleanly.
- U07 (test_ambiguous_write_does_not_send_request): Ambiguous transitions or user assignments
      (multiple matches found) abort with an explicit error and send zero POST/PUT mutation requests.
- U08 (test_timeouts_and_network_errors_are_reported): HTTP timeouts, URLError, and 4xx/5xx return
      non-zero exit codes with clean error diagnostics and zero secret leaks.
- U09 (test_confluence_preserves_body_and_version): Confluence update/append preserves existing
      macros/tables and handles version conflicts cleanly without overwriting.
- U10 (test_file_input_and_json_match_markdown): Body input from file or stdin and JSON/Markdown
      output formatting match semantically without accidental escaping.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ai_governance.tools import confluence, jira

# ── U06: Atlassian Profiles and Pagination ────────────────────────────────────


@patch("urllib.request.urlopen")
def test_atlassian_profiles_and_pagination(
    mock_urlopen, monkeypatch, capsys, tmp_path: Path
) -> None:
    """U06: Search in Jira and Confluence supports pagination and multiple

    configuration profiles cleanly.
    """
    # 1. Profiles support via config file or environment
    profiles_file = tmp_path / "atlassian_profiles.json"
    profiles_data = {
        "work": {
            "url": "https://company.atlassian.net",
            "email": "engineer@work.com",
            "token": "work-api-token",
        },
        "staging": {
            "url": "https://company.atlassian.net",
            "email": "qa@staging.com",
            "token": "staging-api-token",
        },
    }
    profiles_file.write_text(json.dumps(profiles_data), encoding="utf-8")
    monkeypatch.setenv("ATLASSIAN_PROFILES_FILE", str(profiles_file))

    # Switch to "staging" profile
    jira.set_profile("staging")
    confluence.set_profile("staging")
    assert jira._get_base_url() == "https://company.atlassian.net"
    assert confluence._get_base_url() == "https://company.atlassian.net"

    # 2. Jira search pagination
    mock_resp_jira = MagicMock()
    mock_resp_jira.read.return_value = json.dumps(
        {
            "nextPageToken": "page-2",
            "issues": [
                {
                    "key": f"STG-{i}",
                    "fields": {
                        "summary": f"Issue {i}",
                        "status": {"name": "Open"},
                        "issuetype": {"name": "Bug"},
                    },
                }
                for i in range(11, 21)
            ],
        }
    ).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp_jira

    jira.cmd_search("project=STG", page_token="page-1", max_results=10)
    out_jira = capsys.readouterr().out
    assert "STG-11" in out_jira
    assert "page-2" in out_jira
    assert "More results exist" in out_jira

    # 3. Confluence search pagination
    mock_resp_conf = MagicMock()
    mock_resp_conf.read.return_value = json.dumps(
        {
            "start": 15,
            "limit": 15,
            "totalSize": 40,
            "size": 15,
            "results": [
                {"id": f"page-{i}", "title": f"Page {i}", "space": {"key": "ENG"}}
                for i in range(16, 31)
            ],
        }
    ).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp_conf

    confluence.cmd_search("spec", start=15, limit=15)
    out_conf = capsys.readouterr().out
    assert "page-16" in out_conf
    assert "40" in out_conf
    assert "More results exist" in out_conf


# ── U07: Ambiguous Write Does Not Send Request ────────────────────────────────


@patch("urllib.request.urlopen")
def test_ambiguous_write_does_not_send_request(mock_urlopen, monkeypatch, capsys) -> None:
    """U07: Ambiguous transitions or user assignments (multiple matches found)

    abort with an explicit error and send zero POST/PUT mutation requests.
    """
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    # 1. Ambiguous transition (multiple matches e.g. "Review" matches "Peer Review" & "Architecture Review")
    mock_resp_trans = MagicMock()
    mock_resp_trans.read.return_value = json.dumps(
        {
            "transitions": [
                {"id": "11", "name": "Peer Review"},
                {"id": "22", "name": "Architecture Review"},
                {"id": "33", "name": "Done"},
            ]
        }
    ).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp_trans

    with pytest.raises(SystemExit) as exc:
        jira.cmd_transition("TASK-1", "Review")
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "Ambiguous status 'Review'" in err
    assert "Peer Review" in err
    assert "Architecture Review" in err
    # Verify ONLY 1 GET request was made (to list transitions) and ZERO POST mutation requests
    assert mock_urlopen.call_count == 1

    # 2. Ambiguous user assignment (multiple matches found)
    mock_urlopen.reset_mock()
    mock_resp_users = MagicMock()
    mock_resp_users.read.return_value = json.dumps(
        [
            {"accountId": "acc-1", "displayName": "Alex Smith", "emailAddress": "alex.s@co.com"},
            {"accountId": "acc-2", "displayName": "Alex Taylor", "emailAddress": "alex.t@co.com"},
        ]
    ).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp_users

    with pytest.raises(SystemExit) as exc2:
        jira.cmd_assign("TASK-1", "Alex")
    assert exc2.value.code != 0
    err_assign = capsys.readouterr().err
    assert "Ambiguous user 'Alex'" in err_assign
    assert "Alex Smith" in err_assign
    assert "Alex Taylor" in err_assign
    # Verify ONLY 1 GET request was made to search users, and ZERO PUT mutation requests
    assert mock_urlopen.call_count == 1


# ── U08: Timeouts and Network Errors Are Reported ─────────────────────────────


@patch("urllib.request.urlopen")
def test_timeouts_and_network_errors_are_reported(mock_urlopen, monkeypatch, capsys) -> None:
    """U08: HTTP timeouts, URLError, and 4xx/5xx return non-zero exit codes

    with clean error diagnostics and zero secret leaks.
    """
    secret_token = "SUPER_SECRET_JIRA_TOKEN_XYZ123"
    monkeypatch.setenv("ATLASSIAN_EMAIL", "agent@company.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", secret_token)
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    # 1. HTTP 403 Forbidden with sensitive server error body
    http_err = urllib.error.HTTPError(
        url="https://company.atlassian.net/rest/api/3/issue",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=io.BytesIO(f'{{"error": "Unauthorized token: {secret_token}"}}'.encode()),
    )
    mock_urlopen.side_effect = http_err

    assert jira.main(["issue", "SECRET-1"]) != 0
    captured = capsys.readouterr()
    assert "HTTP 403 Error" in captured.err
    # MUST NOT LEAK SECRET TOKEN
    assert secret_token not in captured.err
    assert secret_token not in captured.out
    assert "[REDACTED_TOKEN]" in captured.err

    # 2. Timeout Error
    mock_urlopen.side_effect = TimeoutError(
        f"Connection to https://company.atlassian.net timed out with {secret_token}"
    )
    assert confluence.main(["read", "123"]) != 0
    captured_timeout = capsys.readouterr()
    assert "timed out" in captured_timeout.err.lower()
    assert secret_token not in captured_timeout.err
    assert secret_token not in captured_timeout.out


# ── U09: Confluence Preserves Body and Version ────────────────────────────────


@patch("urllib.request.urlopen")
def test_confluence_preserves_body_and_version(mock_urlopen, monkeypatch, capsys) -> None:
    """U09: Confluence update/append preserves existing macros/tables

    and handles version conflicts cleanly without overwriting.
    """
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    existing_page = {
        "title": "Architecture Guide",
        "space": {"key": "ARCH"},
        "version": {"number": 3},
        "body": {
            "storage": {
                "value": (
                    "<h1>Architecture</h1>"
                    '<ac:structured-macro ac:name="info">'
                    "<ac:rich-text-body><p>Do not bypass security</p></ac:rich-text-body>"
                    "</ac:structured-macro>"
                    "<table><tr><th>Service</th></tr><tr><td>Auth</td></tr></table>"
                )
            }
        },
    }

    # 1. Version conflict check on update: expected v2 but current is v3
    mock_resp_get = MagicMock()
    mock_resp_get.read.return_value = json.dumps(existing_page).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp_get

    with pytest.raises(SystemExit) as exc_ver:
        confluence.cmd_update("1001", "Updated content", expected_version=2)
    assert exc_ver.value.code != 0
    err = capsys.readouterr().err
    assert "Version conflict" in err
    assert "page 1001 is at version 3, expected 2" in err
    # Zero PUT mutation requests sent on version conflict
    assert mock_urlopen.call_count == 1

    # 2. Append preserves existing macro tags and tables in storage format
    mock_urlopen.reset_mock()
    mock_resp_put = MagicMock()
    mock_resp_put.read.return_value = b'{"id": "1001", "version": {"number": 4}}'
    # First call is GET, second call is PUT
    mock_urlopen.return_value.__enter__.side_effect = [mock_resp_get, mock_resp_put]

    confluence.cmd_append("1001", "## New section appended")

    # Inspect the payload sent in the PUT request
    assert mock_urlopen.call_count == 2
    put_call = mock_urlopen.call_args_list[1]
    put_req = put_call.args[0]
    payload_sent = json.loads(put_req.data.decode("utf-8"))

    sent_storage = payload_sent["body"]["storage"]["value"]
    # Existing macros and tables MUST be preserved in storage format
    assert '<ac:structured-macro ac:name="info">' in sent_storage
    assert "<table><tr><th>Service</th></tr>" in sent_storage
    assert "<h2>New section appended</h2>" in sent_storage
    assert payload_sent["version"]["number"] == 4


# ── U10: File Input and JSON Match Markdown ───────────────────────────────────


@patch("urllib.request.urlopen")
def test_file_input_and_json_match_markdown(
    mock_urlopen, monkeypatch, capsys, tmp_path: Path
) -> None:
    """U10: Body input from file or stdin and JSON/Markdown output formatting

    match semantically without accidental escaping.
    """
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")

    # 1. Input from file
    doc_file = tmp_path / "content.md"
    raw_markdown = "## Overview\n\n- Feature A: `print('hello & world')`\n- Quote: \"example\""
    doc_file.write_text(raw_markdown, encoding="utf-8")

    body_from_file = confluence.read_input_text(f"@{doc_file}")
    assert body_from_file == raw_markdown

    # 2. Input from stdin
    monkeypatch.setattr("sys.stdin", io.StringIO("Body from stdin with <brackets> & symbols"))
    body_from_stdin = confluence.read_input_text("-")
    assert body_from_stdin == "Body from stdin with <brackets> & symbols"

    # 3. ADF Markdown bidirectional parsing does NOT double escape ampersands or quotes
    adf = jira.md_to_adf("Check `foo & bar` and **bold**")
    md = jira._adf_to_md(adf)
    assert "`foo & bar`" in md
    assert "**bold**" in md
    assert "&amp;" not in md

    # 4. JSON output formatting matching Markdown data
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {
            "key": "DEV-50",
            "fields": {
                "summary": "Special symbols: <tag> & 'quote'",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
            },
        }
    ).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    jira.cmd_issue("DEV-50", as_json=True)
    out_json = capsys.readouterr().out
    data = json.loads(out_json)
    assert data["fields"]["summary"] == "Special symbols: <tag> & 'quote'"
