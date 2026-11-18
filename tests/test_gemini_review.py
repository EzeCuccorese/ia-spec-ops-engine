"""Tests for the in-house Gemini PR review script."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gemini_review", REPO_ROOT / ".github" / "scripts" / "gemini_review.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gr = _load()


class _FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def test_annotate_diff_tracks_new_lines_across_files_and_hunks() -> None:
    raw = "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "index 111..222 100644",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -1,3 +1,4 @@",
            " def a():",
            "-    return 1",
            "+    return 2",
            "+    # ++ b/not_a_header.py",
            " ",
            "@@ -20,2 +21,3 @@",
            " def b():",
            "+    return 3",
            "diff --git a/README.md b/README.md",
            "--- a/README.md",
            "+++ b/README.md",
            "@@ -5,1 +5,2 @@",
            " title",
            "+subtitle",
        ]
    )

    annotated, valid = gr.annotate_diff(raw)

    assert " L1: def a():" in annotated
    assert "-          return 1" in annotated
    assert "+L2:     return 2" in annotated
    assert "+L3:     # ++ b/not_a_header.py" in annotated
    assert "+L22:     return 3" in annotated
    assert "+L6: subtitle" in annotated
    assert valid == {
        "src/app.py": {2, 3, 22},
        "README.md": {6},
    }


def test_annotate_diff_truncates_at_budget_and_omits_dropped_lines() -> None:
    raw = "\n".join(
        [
            "diff --git a/src/big.py b/src/big.py",
            "--- a/src/big.py",
            "+++ b/src/big.py",
            "@@ -1,1 +1,12 @@",
            *[f"+value_{i} = {'x' * 30}" for i in range(1, 13)],
        ]
    )

    annotated, valid = gr.annotate_diff(raw, max_chars=240)

    assert len(annotated) <= 240
    assert "truncated for review budget" in annotated
    assert valid["src/big.py"]
    assert 12 not in valid["src/big.py"]


def test_snap_comments_handles_exact_snapped_out_of_hunk_and_coercion() -> None:
    raw_comments = [
        {"path": "src/a.py", "line": "L10", "severity": "P1", "body": "Null check needed"},
        {"path": "src/a.py", "line": 12, "severity": "P2", "body": "Off by two"},
        {"path": "src/a.py", "line": 12, "severity": "p2", "body": "Off by two"},
        {"path": "src/a.py", "line": 99, "severity": "P3", "body": "Distant line"},
        {"path": "other.py", "line": 3, "body": "File outside hunk"},
        {"path": "src/a.py", "line": True, "body": "Invalid bool line"},
        {"path": "src/a.py", "line": 0, "body": "Invalid zero line"},
    ]
    filtered = gr._filter_comments(raw_comments)
    inline, out_of_hunk = gr.snap_comments_to_diff(filtered, {"src/a.py": {10}})

    assert inline == [
        {"path": "src/a.py", "line": 10, "body": "**[P1]** Null check needed"},
        {"path": "src/a.py", "line": 10, "body": "**[P2]** Off by two"},
    ]
    assert out_of_hunk == [
        {"path": "src/a.py", "line": 99, "body": "**[P3]** Distant line"},
        {"path": "other.py", "line": 3, "body": "File outside hunk"},
    ]


def test_file_priority_orders_source_before_tests_and_docs() -> None:
    files = [
        "README.md",
        "tests/test_cli.py",
        "pyproject.toml",
        "packages/ai-governance/src/ai_governance/cli.py",
        ".github/scripts/gemini_review.py",
        "packages/workspace/src/tests/helper.py",
    ]
    ordered = sorted(files, key=gr._file_priority)

    assert ordered == [
        ".github/scripts/gemini_review.py",
        "packages/ai-governance/src/ai_governance/cli.py",
        "pyproject.toml",
        "packages/workspace/src/tests/helper.py",
        "tests/test_cli.py",
        "README.md",
    ]


def test_matches_any_filters_globs_and_basenames() -> None:
    patterns = ["*.lock", "dist/*", "package-lock.json"]
    assert gr._matches_any("packages/web/package-lock.json", patterns) is True
    assert gr._matches_any("uv.lock", patterns) is True
    assert gr._matches_any("dist/bundle.js", patterns) is True
    assert gr._matches_any("src/main.py", patterns) is False


@dataclass(frozen=True)
class _ScopeCase:
    reviews: list[dict[str, Any]]
    ancestors: set[str]
    event: tuple[str, str, str, str]
    expected: tuple[str, str]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _ScopeCase(
                [], set(), ("main", "aaaa111", "opened", ""), ("full", "origin/main...HEAD")
            ),
            id="first_review_runs_full",
        ),
        pytest.param(
            _ScopeCase(
                [{"body": "## Gemini Code Review\n\n<!-- gemini-review-sha: aaaa111 -->"}],
                {"aaaa111"},
                ("main", "bbbb222", "synchronize", "aaaa111"),
                ("incremental", "aaaa111..HEAD"),
            ),
            id="synchronize_uses_marker_ancestor_for_incremental",
        ),
        pytest.param(
            _ScopeCase(
                [{"body": "## Gemini Code Review\n\n<!-- gemini-review-sha: bbbb222 -->"}],
                {"bbbb222"},
                ("main", "bbbb222", "synchronize", "aaaa111"),
                ("skip", ""),
            ),
            id="already_reviewed_head_skips",
        ),
        pytest.param(
            _ScopeCase(
                [
                    {
                        "user": {"login": "github-actions[bot]"},
                        "commit_id": "cccc333",
                        "body": "Summary",
                    }
                ],
                {"cccc333"},
                ("main", "dddd444", "synchronize", "cccc333"),
                ("incremental", "cccc333..HEAD"),
            ),
            id="legacy_bot_review_commit_id_fallback",
        ),
        pytest.param(
            _ScopeCase(
                [{"body": "<!-- gemini-review-sha: 1111111 -->"}],
                set(),
                ("main", "dddd444", "synchronize", "2222222"),
                ("full", "origin/main...HEAD"),
            ),
            id="force_push_without_valid_ancestor_runs_full",
        ),
        pytest.param(
            _ScopeCase(
                [{"body": "<!-- gemini-review-sha: bbbb222 -->"}],
                {"bbbb222"},
                ("main", "bbbb222", "labeled", ""),
                ("full", "origin/main...HEAD"),
            ),
            id="labeled_forces_full_review",
        ),
    ],
)
def test_resolve_review_scope(monkeypatch: pytest.MonkeyPatch, case: _ScopeCase) -> None:
    monkeypatch.setattr(gr.urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse(case.reviews))
    monkeypatch.setattr(gr, "_is_valid_ancestor", lambda sha, _head="HEAD": sha in case.ancestors)
    target = gr.ReviewTarget(
        owner="EzeCuccorese", repo="ia-spec-ops-engine", pr_number="82", token="tok"
    )
    event = gr.ReviewEvent(*case.event)

    assert gr.resolve_review_scope(target, event) == case.expected


def test_fetch_last_reviewed_sha_degrades_gracefully_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "https://api.github.com", 500, "err", None, io.BytesIO(b"fail")
        )  # type: ignore[arg-type]

    monkeypatch.setattr(gr.urllib.request, "urlopen", fail)
    target = gr.ReviewTarget(owner="o", repo="r", pr_number="1", token="tok")

    assert gr.fetch_last_reviewed_sha(target) is None


def test_post_github_review_sends_inline_out_of_hunk_and_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_urlopen(req: Any, timeout: int = 30) -> _FakeResponse:
        assert timeout == 30
        captured.append(json.loads(req.data.decode("utf-8")))
        return _FakeResponse({"id": 1}, status=200)

    monkeypatch.setattr(gr.urllib.request, "urlopen", fake_urlopen)
    target = gr.ReviewTarget(owner="o", repo="r", pr_number="7", token="tok")
    meta = gr.ReviewMetadata(
        mode="incremental",
        commit_sha="deadbeef1234",
        out_of_hunk=({"path": "docs.md", "line": 4, "body": "**[P3]** Fix link"},),
    )

    gr.post_github_review(
        target,
        "Checked incremental diff.",
        [{"path": "src/a.py", "line": 10, "body": "**[P1]** Validate input"}],
        meta,
    )

    assert len(captured) == 1
    payload = captured[0]
    assert payload["commit_id"] == "deadbeef1234"
    assert payload["comments"] == [
        {"path": "src/a.py", "line": 10, "body": "**[P1]** Validate input"}
    ]
    assert "## Gemini Code Review (Incremental)" in payload["body"]
    assert "### Notes Outside Diff Hunks" in payload["body"]
    assert "- **docs.md:4**: **[P3]** Fix link" in payload["body"]
    assert "<!-- gemini-review-sha: deadbeef1234 -->" in payload["body"]


def test_post_github_review_falls_back_on_http_422(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[dict[str, Any]] = []

    def fake_urlopen(req: Any, timeout: int = 30) -> _FakeResponse:
        payload = json.loads(req.data.decode("utf-8"))
        posted.append(payload)
        if "comments" in payload:
            raise urllib.error.HTTPError(
                req.full_url,
                422,
                "Unprocessable Entity",
                None,
                io.BytesIO(b"bad line"),  # type: ignore[arg-type]
            )
        return _FakeResponse({"id": 2}, status=200)

    monkeypatch.setattr(gr.urllib.request, "urlopen", fake_urlopen)
    target = gr.ReviewTarget(owner="o", repo="r", pr_number="7", token="tok")
    meta = gr.ReviewMetadata(mode="full", commit_sha="abcd1234")

    gr.post_github_review(
        target,
        "Summary text.",
        [{"path": "src/a.py", "line": 5, "body": "**[P1]** Bug"}],
        meta,
    )

    assert len(posted) == 2
    assert "comments" not in posted[1]
    assert "### Detailed Comments" in posted[1]["body"]
    assert "- **src/a.py:5**: **[P1]** Bug" in posted[1]["body"]
    assert "<!-- gemini-review-sha: abcd1234 -->" in posted[1]["body"]
