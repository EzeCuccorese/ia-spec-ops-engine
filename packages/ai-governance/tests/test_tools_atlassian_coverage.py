"""Additional coverage for ai_governance.tools.jira / confluence.

Focuses on argument parsing (main()) and request-building / response-formatting
functions, mocking the HTTP layer via urllib.request.urlopen (as in
test_tools_atlassian.py). No network access is performed.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from ai_governance.tools import atlassian_common, confluence, jira


@pytest.fixture(autouse=True)
def _atlassian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "test@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "fake_token")
    monkeypatch.setenv("ATLASSIAN_URL", "https://company.atlassian.net")


def _mock_sequence(*bodies: dict | list) -> MagicMock:
    """Builds a urlopen mock that returns each body (as JSON) in sequence."""
    responses = [MagicMock() for _ in bodies]
    for resp, body in zip(responses, bodies, strict=True):
        resp.read.return_value = json.dumps(body).encode()

    mock_urlopen = MagicMock()
    mock_urlopen.return_value.__enter__.side_effect = responses
    return mock_urlopen


# ── jira: command formatting ────────────────────────────────────────────────


def test_jira_cmd_search_table(capsys: pytest.CaptureFixture[str]) -> None:
    body = {
        "issues": [
            {
                "key": "PROJ-1",
                "fields": {
                    "summary": "Fix bug",
                    "status": {"name": "Open"},
                    "assignee": {"displayName": "Alice"},
                    "issuetype": {"name": "Bug"},
                },
            }
        ],
        "total": 5,
        "startAt": 0,
    }
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.cmd_search("project = PROJ")
    out = capsys.readouterr().out
    assert "PROJ-1" in out
    assert "More results exist" in out


def test_jira_cmd_search_no_results(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"issues": [], "total": 0})):
        jira.cmd_search("project = NONE")
    assert "No results found" in capsys.readouterr().out


def test_jira_cmd_search_json(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"issues": [], "total": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.cmd_search("x", as_json=True)
    out = capsys.readouterr().out
    assert json.loads(out) == body


def test_jira_cmd_comments(capsys: pytest.CaptureFixture[str]) -> None:
    comments_body = {
        "comments": [
            {
                "author": {"displayName": "Bob"},
                "created": "2024-01-01T00:00:00.000+0000",
                "id": "10",
                "body": {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]},
            }
        ]
    }
    summary_body = {"fields": {"summary": "A title"}}
    with patch("urllib.request.urlopen", _mock_sequence(comments_body, summary_body)):
        jira.cmd_comments("PROJ-2")
    out = capsys.readouterr().out
    assert "Comments on PROJ-2" in out
    assert "Bob" in out


def test_jira_cmd_comments_empty(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"comments": []})):
        jira.cmd_comments("PROJ-3")
    assert "No comments." in capsys.readouterr().out


def test_jira_cmd_create(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"key": "PROJ-9"})):
        jira.cmd_create("PROJ", "New task", desc="details", issue_type="Task")
    out = capsys.readouterr().out
    assert "PROJ-9" in out


def test_jira_cmd_create_subtask_with_parent(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"key": "PROJ-10"})):
        jira.cmd_create("PROJ", "Child", issue_type="Sub-task", parent="PROJ-1")
    assert "PROJ-10" in capsys.readouterr().out


def test_jira_cmd_comment(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"id": "555"})):
        jira.cmd_comment("PROJ-1", "a **comment**")
    out = capsys.readouterr().out
    assert "Comment added to PROJ-1" in out
    assert "555" in out


def test_jira_cmd_comment_edit(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({})):
        jira.cmd_comment_edit("PROJ-1", "555", "updated text")
    assert "Comment 555 edited on PROJ-1" in capsys.readouterr().out


def test_jira_cmd_transition_exact_match(capsys: pytest.CaptureFixture[str]) -> None:
    transitions = {
        "transitions": [{"id": "31", "name": "Done"}, {"id": "21", "name": "In Progress"}]
    }
    with patch("urllib.request.urlopen", _mock_sequence(transitions, {})):
        jira.cmd_transition("PROJ-1", "done")
    assert "PROJ-1 → Done" in capsys.readouterr().out


def test_jira_cmd_transition_not_found() -> None:
    transitions = {"transitions": [{"id": "31", "name": "Done"}]}
    with patch("urllib.request.urlopen", _mock_sequence(transitions)), pytest.raises(SystemExit):
        jira.cmd_transition("PROJ-1", "nonexistent")


def test_jira_cmd_transition_ambiguous() -> None:
    transitions = {
        "transitions": [
            {"id": "1", "name": "In Review"},
            {"id": "2", "name": "In Progress"},
        ]
    }
    with patch("urllib.request.urlopen", _mock_sequence(transitions)), pytest.raises(SystemExit):
        jira.cmd_transition("PROJ-1", "In")


def test_jira_cmd_assign_me(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"accountId": "abc123"}, {})):
        jira.cmd_assign("PROJ-1", "me")
    assert "assigned to you" in capsys.readouterr().out


def test_jira_cmd_assign_exact_email(capsys: pytest.CaptureFixture[str]) -> None:
    users = [{"accountId": "u1", "displayName": "Carol", "emailAddress": "carol@example.com"}]
    with patch("urllib.request.urlopen", _mock_sequence(users, {})):
        jira.cmd_assign("PROJ-1", "carol@example.com")
    assert "assigned to carol@example.com" in capsys.readouterr().out


def test_jira_cmd_assign_not_found() -> None:
    with patch("urllib.request.urlopen", _mock_sequence([])), pytest.raises(SystemExit):
        jira.cmd_assign("PROJ-1", "ghost@example.com")


def test_jira_cmd_assign_ambiguous() -> None:
    users = [
        {"accountId": "u1", "displayName": "Carol A", "emailAddress": "a@example.com"},
        {"accountId": "u2", "displayName": "Carol B", "emailAddress": "b@example.com"},
    ]
    with patch("urllib.request.urlopen", _mock_sequence(users)), pytest.raises(SystemExit):
        jira.cmd_assign("PROJ-1", "carol")


def test_jira_cmd_sprint_active(capsys: pytest.CaptureFixture[str]) -> None:
    boards = {"values": [{"id": 7}]}
    sprints = {"values": [{"id": 99, "name": "Sprint 5", "state": "active"}]}
    with patch("urllib.request.urlopen", _mock_sequence(boards, sprints, {})):
        jira.cmd_sprint("PROJ-1", "active")
    assert "Sprint 5" in capsys.readouterr().out


def test_jira_cmd_sprint_no_boards() -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"values": []})), pytest.raises(SystemExit):
        jira.cmd_sprint("PROJ-1", "active")


def test_jira_cmd_sprint_no_active() -> None:
    boards = {"values": [{"id": 7}]}
    sprints = {"values": [{"id": 1, "name": "Sprint 1", "state": "closed"}]}
    with (
        patch("urllib.request.urlopen", _mock_sequence(boards, sprints)),
        pytest.raises(SystemExit),
    ):
        jira.cmd_sprint("PROJ-1", "active")


def test_jira_table_helpers() -> None:
    assert jira._is_table_separator("| --- | --- |")
    assert not jira._is_table_separator("| a | b |")
    assert jira._parse_table_row("| a | b |") == ["a", "b"]
    adf = jira._table_to_adf(["| a | b |", "| c | d |"])
    assert adf["type"] == "table"
    assert len(adf["content"]) == 2


def test_jira_md_to_adf_table() -> None:
    md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    adf = jira._md_to_adf(md)
    assert adf["content"][0]["type"] == "table"


def test_jira_cmd_help(capsys: pytest.CaptureFixture[str]) -> None:
    jira.cmd_help()
    assert "jira — Lightweight CLI" in capsys.readouterr().out


# ── jira: main() argument parsing ───────────────────────────────────────────


def test_jira_main_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    jira.main([])
    assert "jira — Lightweight CLI" in capsys.readouterr().out


def test_jira_main_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    jira.main(["--help"])
    assert "jira — Lightweight CLI" in capsys.readouterr().out


def test_jira_main_issue(capsys: pytest.CaptureFixture[str]) -> None:
    body = {
        "fields": {"summary": "Something", "status": {"name": "Open"}, "issuetype": {"name": "Bug"}}
    }
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.main(["issue", "PROJ-1"])
    assert "[PROJ-1]" in capsys.readouterr().out


def test_jira_main_unknown_command() -> None:
    with pytest.raises(SystemExit):
        jira.main(["frobnicate"])


def test_jira_main_create_with_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"key": "PROJ-5"})):
        jira.main(
            [
                "create",
                "PROJ",
                "Title text",
                "--desc",
                "the body",
                "--type",
                "Bug",
                "--parent",
                "PROJ-0",
            ]
        )
    assert "PROJ-5" in capsys.readouterr().out


def test_jira_main_profile_flag(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"fields": {"summary": "X", "status": {"name": "Open"}, "issuetype": {"name": "Task"}}}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.main(["--profile", "work", "issue", "PROJ-1"])
    assert "[PROJ-1]" in capsys.readouterr().out
    jira.set_profile(None)  # reset global state for other tests


# ── confluence: command formatting ──────────────────────────────────────────


def test_confluence_cmd_search(capsys: pytest.CaptureFixture[str]) -> None:
    body = {
        "results": [{"id": "1", "title": "Doc", "space": {"key": "ENG"}}],
        "totalSize": 1,
    }
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.cmd_search("architecture")
    out = capsys.readouterr().out
    assert "Doc" in out


def test_confluence_cmd_search_no_results(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"results": [], "totalSize": 0})):
        confluence.cmd_search("nothing")
    assert "No results found" in capsys.readouterr().out


def test_confluence_cmd_search_json(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"results": [], "totalSize": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.cmd_search("q", as_json=True)
    assert json.loads(capsys.readouterr().out) == body


def test_confluence_cmd_spaces(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"results": [{"key": "ENG", "name": "Engineering"}]}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.cmd_spaces()
    assert "Engineering" in capsys.readouterr().out


def test_confluence_cmd_spaces_empty(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"results": []})):
        confluence.cmd_spaces()
    assert "No spaces found" in capsys.readouterr().out


def test_confluence_cmd_create(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"id": "42"})):
        confluence.cmd_create("ENG", "New Page", "# Heading\n\nBody")
    out = capsys.readouterr().out
    assert "New Page" in out
    assert "42" in out


def test_confluence_cmd_create_with_parent(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"id": "43"})):
        confluence.cmd_create("ENG", "Child Page", "content", parent_id="42")
    assert "43" in capsys.readouterr().out


def test_confluence_cmd_update(capsys: pytest.CaptureFixture[str]) -> None:
    current = {"title": "Doc", "space": {"key": "ENG"}, "version": {"number": 3}}
    with patch("urllib.request.urlopen", _mock_sequence(current, {})):
        confluence.cmd_update("42", "new body text")
    assert "v4" in capsys.readouterr().out


def test_confluence_cmd_update_version_conflict() -> None:
    current = {"title": "Doc", "space": {"key": "ENG"}, "version": {"number": 3}}
    with patch("urllib.request.urlopen", _mock_sequence(current)), pytest.raises(SystemExit):
        confluence.cmd_update("42", "new body", expected_version=2)


def test_confluence_cmd_append(capsys: pytest.CaptureFixture[str]) -> None:
    current = {
        "title": "Doc",
        "space": {"key": "ENG"},
        "version": {"number": 1},
        "body": {"storage": {"value": "<p>old</p>"}},
    }
    with patch("urllib.request.urlopen", _mock_sequence(current, {})):
        confluence.cmd_append("42", "more text")
    assert "v2" in capsys.readouterr().out


def test_confluence_cmd_append_version_conflict() -> None:
    current = {
        "title": "Doc",
        "space": {"key": "ENG"},
        "version": {"number": 5},
        "body": {"storage": {"value": ""}},
    }
    with patch("urllib.request.urlopen", _mock_sequence(current)), pytest.raises(SystemExit):
        confluence.cmd_append("42", "text", expected_version=1)


def test_confluence_cmd_comment(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({})):
        confluence.cmd_comment("42", "a comment")
    assert "Comment added to page 42" in capsys.readouterr().out


def test_confluence_cmd_help(capsys: pytest.CaptureFixture[str]) -> None:
    confluence.cmd_help()
    assert "confluence — Lightweight CLI" in capsys.readouterr().out


def test_confluence_md_to_storage_lists_and_rules() -> None:
    storage = confluence.md_to_storage("- one\n- two\n\n---\n")
    assert "<ul><li>one</li><li>two</li></ul>" in storage
    assert "<hr/>" in storage


def test_confluence_html_to_md_table() -> None:
    html_str = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    md = confluence.html_to_md(html_str)
    assert "| A | B |" in md
    assert "| 1 | 2 |" in md


# ── confluence: main() argument parsing ─────────────────────────────────────


def test_confluence_main_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    confluence.main([])
    assert "confluence — Lightweight CLI" in capsys.readouterr().out


def test_confluence_main_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    confluence.main(["--help"])
    assert "confluence — Lightweight CLI" in capsys.readouterr().out


def test_confluence_main_read(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"title": "T", "body": {"storage": {"value": "<p>hi</p>"}}, "space": {"key": "ENG"}}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.main(["read", "42"])
    assert "# T" in capsys.readouterr().out


def test_confluence_main_search_with_space_flag(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"results": [], "totalSize": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.main(["search", "term", "--space", "ENG"])
    assert "No results found" in capsys.readouterr().out


def test_confluence_main_unknown_command() -> None:
    with pytest.raises(SystemExit):
        confluence.main(["bogus"])


def test_confluence_main_create_with_parent_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"id": "9"})):
        confluence.main(["create", "ENG", "Title", "Body text", "--parent", "1"])
    assert "9" in capsys.readouterr().out


def test_confluence_main_update_with_version_flag() -> None:
    current = {"title": "Doc", "space": {"key": "ENG"}, "version": {"number": 3}}
    with patch("urllib.request.urlopen", _mock_sequence(current)), pytest.raises(SystemExit):
        confluence.main(["update", "42", "new text", "--version", "1"])


# ── jira: ADF rendering branches ────────────────────────────────────────────


def test_jira_adf_to_md_empty_and_non_dict() -> None:
    assert jira._adf_to_md(None) == ""
    assert jira._adf_to_md("not-a-dict") == ""


def test_jira_adf_to_md_marks() -> None:
    node = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "em", "marks": [{"type": "em"}]},
            {"type": "text", "text": "code", "marks": [{"type": "code"}]},
            {"type": "text", "text": "strike", "marks": [{"type": "strike"}]},
            {
                "type": "text",
                "text": "link",
                "marks": [{"type": "link", "attrs": {"href": "https://x"}}],
            },
        ],
    }
    md = jira._adf_to_md(node)
    assert "*em*" in md
    assert "`code`" in md
    assert "~~strike~~" in md
    assert "[link](https://x)" in md


def test_jira_adf_to_md_block_types() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Title"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "a"}]}
                        ],
                    }
                ],
            },
            {
                "type": "orderedList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "b"}]}
                        ],
                    }
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "python"},
                "content": [{"type": "text", "text": "print(1)"}],
            },
            {
                "type": "blockquote",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "quoted"}]}],
            },
            {"type": "rule"},
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "H1"}],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "C1"}],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
        ],
    }
    md = jira._adf_to_md(doc)
    assert "## Title" in md
    assert "- a" in md
    assert "1. b" in md
    assert "```python" in md
    assert "> quoted" in md
    assert "---" in md
    assert "| H1 |" in md
    assert "| C1 |" in md


def test_jira_fmt_date_invalid_and_missing() -> None:
    assert jira._fmt_date(None) == "—"
    assert jira._fmt_date("not-a-date-at-all") == "not-a-date-at-all"[:16]


def test_jira_inline_to_adf_code() -> None:
    nodes = jira._inline_to_adf("plain `code` end")
    marks = [n.get("marks", [{}])[0].get("type") for n in nodes if n.get("marks")]
    assert "code" in marks


def test_jira_parse_table_row_no_pipes() -> None:
    assert jira._parse_table_row("a | b") == ["a", "b"]


def test_jira_md_to_adf_single_row_table_fallback() -> None:
    adf = jira._md_to_adf("| just one row |")
    assert adf["content"][0]["type"] == "paragraph"


def test_jira_md_to_adf_bullets_then_blank_line() -> None:
    adf = jira._md_to_adf("- one\n- two\n\nmore text")
    types = [c["type"] for c in adf["content"]]
    assert types == ["bulletList", "paragraph"]


# ── jira: command formatting (additional branches) ──────────────────────────


def test_jira_cmd_issue_json(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"fields": {"summary": "S"}}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.cmd_issue("PROJ-1", as_json=True)
    assert json.loads(capsys.readouterr().out) == body


def test_jira_cmd_issue_with_comments(capsys: pytest.CaptureFixture[str]) -> None:
    body = {
        "fields": {
            "summary": "S",
            "status": {"name": "Open"},
            "issuetype": {"name": "Task"},
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Dana"},
                        "created": "2024-01-01T00:00:00.000+0000",
                        "body": {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]},
                    }
                ]
            },
        }
    }
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.cmd_issue("PROJ-1")
    out = capsys.readouterr().out
    assert "Recent Comments" in out
    assert "Dana" in out


def test_jira_cmd_search_exact_total(capsys: pytest.CaptureFixture[str]) -> None:
    body = {
        "issues": [
            {
                "key": "PROJ-1",
                "fields": {
                    "summary": "s",
                    "status": {"name": "Open"},
                    "assignee": None,
                    "issuetype": {"name": "Task"},
                },
            }
        ],
        "total": 1,
        "startAt": 0,
    }
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.cmd_search("q")
    assert "More results exist" not in capsys.readouterr().out


def test_jira_cmd_comments_json(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"comments": [{"id": "1"}]}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.cmd_comments("PROJ-1", as_json=True)
    assert json.loads(capsys.readouterr().out) == body


def test_jira_cmd_transition_single_substring(capsys: pytest.CaptureFixture[str]) -> None:
    transitions = {"transitions": [{"id": "5", "name": "In Progress"}]}
    with patch("urllib.request.urlopen", _mock_sequence(transitions, {})):
        jira.cmd_transition("PROJ-1", "progress")
    assert "In Progress" in capsys.readouterr().out


def test_jira_cmd_assign_single_result_not_exact(capsys: pytest.CaptureFixture[str]) -> None:
    users = [{"accountId": "u9", "displayName": "Zara Q", "emailAddress": "zara@example.com"}]
    with patch("urllib.request.urlopen", _mock_sequence(users, {})):
        jira.cmd_assign("PROJ-1", "zar")
    assert "assigned to zar" in capsys.readouterr().out


def test_jira_cmd_sprint_not_found() -> None:
    boards = {"values": [{"id": 1}]}
    sprints = {"values": [{"name": "Alpha", "state": "closed", "id": 1}]}
    with (
        patch("urllib.request.urlopen", _mock_sequence(boards, sprints)),
        pytest.raises(SystemExit),
    ):
        jira.cmd_sprint("PROJ-1", "zzz")


def test_jira_cmd_sprint_ambiguous() -> None:
    boards = {"values": [{"id": 1}]}
    sprints = {
        "values": [
            {"name": "Sprint Alpha", "state": "active", "id": 1},
            {"name": "Sprint Alpha Two", "state": "future", "id": 2},
        ]
    }
    with (
        patch("urllib.request.urlopen", _mock_sequence(boards, sprints)),
        pytest.raises(SystemExit),
    ):
        jira.cmd_sprint("PROJ-1", "alpha")


def test_jira_cmd_sprint_single_match(capsys: pytest.CaptureFixture[str]) -> None:
    boards = {"values": [{"id": 1}]}
    sprints = {"values": [{"name": "Sprint Beta", "state": "future", "id": 3}]}
    with patch("urllib.request.urlopen", _mock_sequence(boards, sprints, {})):
        jira.cmd_sprint("PROJ-1", "beta")
    assert "Sprint Beta" in capsys.readouterr().out


# ── jira: main() argument parsing (additional branches) ────────────────────


def test_jira_main_json_flag(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"issues": [], "total": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.main(["search", "q", "--json"])
    assert json.loads(capsys.readouterr().out) == body


def test_jira_main_search_start_at_flag(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"issues": [], "total": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.main(["search", "q", "--start-at", "5"])
    assert "No results found" in capsys.readouterr().out


def test_jira_main_max_results_flag(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"issues": [], "total": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        jira.main(["search", "q", "--max-results", "10"])
    assert "No results found" in capsys.readouterr().out


def test_jira_main_file_flag_comment(capsys: pytest.CaptureFixture[str], tmp_path) -> None:
    f = tmp_path / "body.txt"
    f.write_text("file body")
    with patch("urllib.request.urlopen", _mock_sequence({"id": "1"})):
        jira.main(["comment", "PROJ-1", "--file", str(f)])
    assert "Comment added to PROJ-1" in capsys.readouterr().out


def test_jira_main_comments_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"comments": []})):
        jira.main(["comments", "PROJ-1"])
    assert "No comments." in capsys.readouterr().out


def test_jira_main_comment_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"id": "1"})):
        jira.main(["comment", "PROJ-1", "text"])
    assert "Comment added to PROJ-1" in capsys.readouterr().out


def test_jira_main_comment_edit_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({})):
        jira.main(["comment-edit", "PROJ-1", "5", "new text"])
    assert "Comment 5 edited on PROJ-1" in capsys.readouterr().out


def test_jira_main_transition_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    transitions = {"transitions": [{"id": "1", "name": "Done"}]}
    with patch("urllib.request.urlopen", _mock_sequence(transitions, {})):
        jira.main(["transition", "PROJ-1", "done"])
    assert "PROJ-1 → Done" in capsys.readouterr().out


def test_jira_main_assign_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"accountId": "abc"}, {})):
        jira.main(["assign", "PROJ-1", "me"])
    assert "assigned to you" in capsys.readouterr().out


def test_jira_main_sprint_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    boards = {"values": [{"id": 1}]}
    sprints = {"values": [{"id": 2, "name": "Sprint X", "state": "active"}]}
    with patch("urllib.request.urlopen", _mock_sequence(boards, sprints, {})):
        jira.main(["sprint", "PROJ-1", "active"])
    assert "Sprint X" in capsys.readouterr().out


def test_jira_main_create_rejects_extra_tokens(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        jira.main(["create", "PROJ", "Title", "extra-token", "--type", "Bug"])
    assert exc.value.code == 2 and "unrecognized arguments: extra-token" in capsys.readouterr().err


# ── confluence: HTML/Markdown rendering branches ────────────────────────────


def test_confluence_html_to_md_empty() -> None:
    assert confluence.html_to_md("") == ""


def test_confluence_html_to_md_table_no_rows() -> None:
    md = confluence.html_to_md("<table><tbody></tbody></table>")
    assert "|" not in md


def test_confluence_md_to_storage_passthrough_html_lines() -> None:
    md = "<table>\n<tr><td>x</td></tr>\n</table>\n<ac:structured-macro/>"
    storage = confluence.md_to_storage(md)
    assert "<table>" in storage
    assert "<ac:structured-macro/>" in storage


# ── confluence: command formatting (additional branches) ───────────────────


def test_confluence_cmd_read_json(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"title": "T"}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.cmd_read("1", as_json=True)
    assert json.loads(capsys.readouterr().out) == body


def test_confluence_cmd_spaces_json(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"results": []}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.cmd_spaces(as_json=True)
    assert json.loads(capsys.readouterr().out) == body


# ── confluence: main() argument parsing (additional branches) ──────────────


def test_confluence_main_pagination_flags(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"results": [], "totalSize": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.main(["search", "q", "--start", "2", "--limit", "5"])
    assert "No results found" in capsys.readouterr().out


def test_confluence_main_version_flag_no_conflict(capsys: pytest.CaptureFixture[str]) -> None:
    current = {"title": "Doc", "space": {"key": "ENG"}, "version": {"number": 3}}
    with patch("urllib.request.urlopen", _mock_sequence(current, {})):
        confluence.main(["update", "42", "text", "--version", "3"])
    assert "v4" in capsys.readouterr().out


def test_confluence_main_file_flag(capsys: pytest.CaptureFixture[str], tmp_path) -> None:
    f = tmp_path / "body.txt"
    f.write_text("body from file")
    with patch("urllib.request.urlopen", _mock_sequence({"id": "9"})):
        confluence.main(["create", "ENG", "Title", "--file", str(f)])
    assert "9" in capsys.readouterr().out


def test_confluence_main_spaces_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({"results": []})):
        confluence.main(["spaces"])
    assert "No spaces found" in capsys.readouterr().out


def test_confluence_main_append_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    current = {
        "title": "Doc",
        "space": {"key": "ENG"},
        "version": {"number": 1},
        "body": {"storage": {"value": ""}},
    }
    with patch("urllib.request.urlopen", _mock_sequence(current, {})):
        confluence.main(["append", "42", "more"])
    assert "v2" in capsys.readouterr().out


def test_confluence_main_comment_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("urllib.request.urlopen", _mock_sequence({})):
        confluence.main(["comment", "42", "a comment"])
    assert "Comment added to page 42" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv", [["search", "term", "--space"], ["create", "ENG", "Title", "Body", "--parent"]]
)
def test_confluence_main_flag_without_value_is_an_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        confluence.main(argv)
    assert exc.value.code == 2 and "expected one argument" in capsys.readouterr().err


# ── atlassian_common: profile resolution branches ───────────────────────────


def test_load_profile_config_memory_override() -> None:
    atlassian_common._PROFILE_OVERRIDES["memprofile"] = {
        "email": "e@x.com",
        "token": "tok",
        "url": "https://company.atlassian.net",
    }
    try:
        cfg = atlassian_common.load_profile_config("memprofile")
        assert cfg["email"] == "e@x.com"
    finally:
        atlassian_common._PROFILE_OVERRIDES.pop("memprofile", None)


def test_load_profile_config_from_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles_file = tmp_path / "profiles.json"
    profiles_file.write_text(
        json.dumps(
            {
                "teamA": {
                    "email": "a@x.com",
                    "api_token": "tok123",
                    "url": "https://company.atlassian.net/",
                }
            }
        )
    )
    monkeypatch.setenv("ATLASSIAN_PROFILES_FILE", str(profiles_file))
    cfg = atlassian_common.load_profile_config("teamA")
    assert cfg["email"] == "a@x.com"
    assert cfg["token"] == "tok123"
    assert cfg["url"] == "https://company.atlassian.net"


def test_load_profile_config_invalid_json_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles_file = tmp_path / "profiles.json"
    profiles_file.write_text("{not valid json")
    monkeypatch.setenv("ATLASSIAN_PROFILES_FILE", str(profiles_file))
    # Falls through past the broken file to the environment-variable fallback.
    cfg = atlassian_common.load_profile_config("teamB")
    assert "email" in cfg


# ── atlassian_common: read_input_text branches ──────────────────────────────


def test_read_input_text_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("piped text"))
    assert atlassian_common.read_input_text("-") == "piped text"


def test_read_input_text_at_file(tmp_path) -> None:
    f = tmp_path / "body.txt"
    f.write_text("file content")
    assert atlassian_common.read_input_text(f"@{f}") == "file content"


def test_read_input_text_plain_existing_path(tmp_path) -> None:
    f = tmp_path / "body2.txt"
    f.write_text("more content")
    assert atlassian_common.read_input_text(str(f)) == "more content"


def test_read_input_text_literal() -> None:
    assert atlassian_common.read_input_text("just text") == "just text"


# ── atlassian_common: execute_request error branches ────────────────────────


@patch("urllib.request.urlopen")
def test_execute_request_http_error_json_body(mock_urlopen: MagicMock) -> None:
    err_resp = MagicMock()
    err_resp.read.return_value = json.dumps({"errorMessages": ["Bad request"]}).encode()
    mock_urlopen.side_effect = urllib.error.HTTPError("http://x", 400, "Bad Request", {}, err_resp)
    with pytest.raises(SystemExit):
        atlassian_common.execute_request("GET", "http://x")


@patch("urllib.request.urlopen")
def test_execute_request_http_error_non_json_body(mock_urlopen: MagicMock) -> None:
    err_resp = MagicMock()
    err_resp.read.return_value = b"plain text error"
    mock_urlopen.side_effect = urllib.error.HTTPError("http://x", 500, "Server Error", {}, err_resp)
    with pytest.raises(SystemExit):
        atlassian_common.execute_request("GET", "http://x")


@patch("urllib.request.urlopen")
def test_execute_request_timeout_error(mock_urlopen: MagicMock) -> None:
    mock_urlopen.side_effect = TimeoutError("timed out")
    with pytest.raises(SystemExit):
        atlassian_common.execute_request("GET", "http://x")


# ── remaining branch coverage ────────────────────────────────────────────────


def test_jira_adf_to_md_multiple_marks_on_one_text() -> None:
    """Exercises the marks for-loop continuing to the next mark after an unrecognized one."""
    node = {
        "type": "text",
        "text": "hi",
        "marks": [{"type": "unknown"}, {"type": "strong"}],
    }
    md = jira._adf_to_md(node)
    assert md == "**hi**"


def test_jira_adf_to_md_table_single_row() -> None:
    """A one-row table skips the header-separator insertion branch."""
    node = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableHeader",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "H1"}]}
                        ],
                    }
                ],
            }
        ],
    }
    md = jira._adf_to_md(node)
    assert md.strip() == "| H1 |"


def test_jira_main_only_flags_no_command(capsys: pytest.CaptureFixture[str]) -> None:
    jira.main(["--json"])
    assert "jira — Lightweight CLI" in capsys.readouterr().out


def test_confluence_html_to_md_table_single_row() -> None:
    md = confluence.html_to_md("<table><tr><th>A</th></tr></table>")
    assert "| A |" in md
    assert "---" not in md


def test_confluence_main_profile_flag(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"title": "T"}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.main(["--profile", "work", "read", "1"])
    assert "# T" in capsys.readouterr().out
    confluence.set_profile(None)  # reset global state for other tests


def test_confluence_main_json_flag(capsys: pytest.CaptureFixture[str]) -> None:
    body = {"results": [], "totalSize": 0}
    with patch("urllib.request.urlopen", _mock_sequence(body)):
        confluence.main(["search", "q", "--json"])
    assert json.loads(capsys.readouterr().out) == body


def test_confluence_main_only_flags_no_command(capsys: pytest.CaptureFixture[str]) -> None:
    confluence.main(["--json"])
    assert "confluence — Lightweight CLI" in capsys.readouterr().out


def test_load_profile_config_from_file_target_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile file exists and parses, but the requested profile key is absent."""
    profiles_file = tmp_path / "profiles.json"
    profiles_file.write_text(json.dumps({"other": {"email": "o@x.com"}}))
    monkeypatch.setenv("ATLASSIAN_PROFILES_FILE", str(profiles_file))
    cfg = atlassian_common.load_profile_config("teamC")
    assert "email" in cfg


def test_read_input_text_at_missing_file_falls_back_to_literal() -> None:
    assert atlassian_common.read_input_text("@no-such-file.txt") == "@no-such-file.txt"
