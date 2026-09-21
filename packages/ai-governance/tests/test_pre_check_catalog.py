from pathlib import Path

from ai_governance.frugality.pre_check import PreCheck, catalog_patterns
from ai_governance.rules.core.catalog import RuleCatalog


def test_catalog_patterns_returns_non_empty_tuple() -> None:
    """catalog_patterns should return a non-empty tuple of patterns from tools."""
    catalog = RuleCatalog()
    patterns = catalog_patterns(catalog.tools)

    assert isinstance(patterns, tuple)
    assert len(patterns) > 0

    for pattern_id, matcher, advice in patterns:
        assert isinstance(pattern_id, str)
        assert pattern_id.startswith("tool:")
        assert callable(matcher)
        assert isinstance(advice, str)
        assert "Deterministic alternative:" in advice
        assert "⚙" in advice


def test_catalog_patterns_ws_worktree_matches() -> None:
    """git worktree add should trigger the ws-worktree tool pattern."""
    catalog = RuleCatalog()
    patterns = catalog_patterns(catalog.tools)

    advice = PreCheck.check_command("git worktree add ../x", extra_patterns=patterns)
    assert advice is not None
    assert "ws worktree" in advice
    assert "⚙ ws-worktree" in advice


def test_catalog_patterns_docker_logs_without_tail() -> None:
    """docker logs without --tail should trigger a warning; with --tail should not."""
    catalog = RuleCatalog()
    patterns = catalog_patterns(catalog.tools)

    # Without --tail should trigger
    advice_no_tail = PreCheck.check_command("docker logs mycontainer", extra_patterns=patterns)
    assert advice_no_tail is not None
    assert "--tail" in advice_no_tail

    # With --tail should not trigger
    advice_with_tail = PreCheck.check_command(
        "docker logs --tail 100 mycontainer", extra_patterns=patterns
    )
    assert advice_with_tail is None


def test_builtins_take_precedence_over_catalog_patterns() -> None:
    """Built-in patterns should be checked before catalog patterns."""
    catalog = RuleCatalog()
    patterns = catalog_patterns(catalog.tools)

    # cat package-lock.json should trigger the built-in lockfile pattern
    advice = PreCheck.check_command("cat package-lock.json", extra_patterns=patterns)
    assert advice is not None
    assert "lockfile" in advice.lower() or "rg" in advice


def test_cat_readme_returns_none() -> None:
    """cat README.md should not trigger any pattern (noisy cat pattern was removed)."""
    catalog = RuleCatalog()
    patterns = catalog_patterns(catalog.tools)

    advice = PreCheck.check_command("cat README.md", extra_patterns=patterns)
    assert advice is None


def test_session_dedup_same_pattern_once(tmp_path: Path) -> None:
    """Same pattern should only be returned once per session."""
    catalog = RuleCatalog()
    patterns = catalog_patterns(catalog.tools)

    # First call should return advice
    advice1 = PreCheck.check_command(
        "cat package-lock.json",
        session_id="s",
        runtime_dir=tmp_path,
        extra_patterns=patterns,
    )
    assert advice1 is not None

    # Second call with same session should return None (deduped)
    advice2 = PreCheck.check_command(
        "cat package-lock.json",
        session_id="s",
        runtime_dir=tmp_path,
        extra_patterns=patterns,
    )
    assert advice2 is None


def test_nofrugal_comment_suppresses_check() -> None:
    """Commands with #nofrugal should not trigger any pattern."""
    catalog = RuleCatalog()
    patterns = catalog_patterns(catalog.tools)

    advice = PreCheck.check_command("cat package-lock.json #nofrugal", extra_patterns=patterns)
    assert advice is None
