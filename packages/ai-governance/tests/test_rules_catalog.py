from ai_governance.rules.catalog import RuleCatalog


def test_catalog_loads_all_rules_with_metadata() -> None:
    catalog = RuleCatalog()
    assert len(catalog.rules) == 28
    for rule in catalog.rules:
        assert rule.description and rule.globs and rule.sha256
        assert rule.content.startswith("# ")


def test_select_general_plus_detected_stacks() -> None:
    catalog = RuleCatalog()
    ids = {rule.id for rule in catalog.select({"java", "docker"})}
    assert {"java-spring", "docker-containers", "01-clean-code-solid"} <= ids
    assert "python-async" not in ids and "react-frontend" not in ids


def test_select_extra_and_excluded() -> None:
    catalog = RuleCatalog()
    ids = {
        r.id
        for r in catalog.select(set(), extra=("go-idiomatic",), excluded=("06-security-privacy",))
    }
    assert "go-idiomatic" in ids
    assert "06-security-privacy" not in ids


def test_no_ai_attribution_policy_remains() -> None:
    text = "\n".join(rule.content for rule in RuleCatalog().rules)
    assert "AI MENTIONS" not in text
