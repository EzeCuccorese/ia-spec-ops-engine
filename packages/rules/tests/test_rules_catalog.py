from rules.core.catalog import RuleCatalog


def test_catalog_loads_all_canonical_rules() -> None:
    catalog = RuleCatalog()
    assert len(catalog.rules) >= 25

    categories = catalog.by_category()
    assert "1-core" in categories
    assert "2-stacks" in categories
    assert "3-infrastructure" in categories
    assert "4-docs" in categories


def test_every_rule_has_valid_metadata_and_invariants() -> None:
    catalog = RuleCatalog()
    for rule in catalog.rules:
        assert rule.id
        assert rule.description
        assert len(rule.globs) > 0
        assert rule.content.startswith("# ")
        assert len(rule.content) > 100
        assert rule.sha256
