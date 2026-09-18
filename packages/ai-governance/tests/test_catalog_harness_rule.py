import json

from ai_governance.rules.core.catalog import RuleCatalog


def test_deterministic_first_rule_exists() -> None:
    """00-deterministic-first rule should exist in the catalog."""
    catalog = RuleCatalog()
    rule = catalog.get("00-deterministic-first")

    assert rule is not None
    assert rule.id == "00-deterministic-first"


def test_deterministic_first_rule_category_and_globs() -> None:
    """00-deterministic-first should be in 0-harness category with **/* glob."""
    catalog = RuleCatalog()
    rule = catalog.get("00-deterministic-first")

    assert rule is not None
    assert rule.category == "0-harness"
    assert rule.globs == ("**/*",)


def test_deterministic_first_rule_content_contains_key_phrases() -> None:
    """Rule content should contain announce symbol, --json, git diff --stat, and tail -40."""
    catalog = RuleCatalog()
    rule = catalog.get("00-deterministic-first")

    assert rule is not None
    assert "⚙" in rule.content
    assert "--json" in rule.content
    assert "git diff --stat" in rule.content
    assert "tail -40" in rule.content


def test_manifest_total_rules_matches_catalog_length() -> None:
    """Manifest total_rules should equal the number of loaded rules."""
    catalog = RuleCatalog()
    manifest_path = catalog.root / "manifest.json"

    assert manifest_path.exists()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_data["total_rules"] == len(catalog.rules)


def test_harness_category_contains_exactly_one_rule() -> None:
    """0-harness category should contain exactly one rule."""
    catalog = RuleCatalog()
    by_category = catalog.by_category()

    assert "0-harness" in by_category
    harness_rules = by_category["0-harness"]
    assert len(harness_rules) == 1


def test_deterministic_first_is_first_rule_in_catalog() -> None:
    """00-deterministic-first should be the first rule in catalog.rules."""
    catalog = RuleCatalog()

    assert len(catalog.rules) > 0
    assert catalog.rules[0].id == "00-deterministic-first"
