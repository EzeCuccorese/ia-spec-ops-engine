import json

import pytest
from ai_governance.rules.catalog import SCHEMA_VERSION, RuleCatalog


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


def test_catalog_profiles() -> None:
    catalog = RuleCatalog()
    assert catalog.profiles == {
        "architecture": "Clean/hexagonal architecture, DDD, refactoring and strangler fig",
        "distributed": "Event-driven architecture, resilience, concurrency and locking",
        "api": "API design and observability",
    }


def test_select_without_profiles_excludes_profiled_rules() -> None:
    catalog = RuleCatalog()
    ids = {rule.id for rule in catalog.select(set())}
    assert "02-clean-architecture-hexagonal" not in ids
    assert "07-event-driven-architecture" not in ids


def test_select_with_architecture_profile() -> None:
    catalog = RuleCatalog()
    ids = {rule.id for rule in catalog.select(set(), profiles=("architecture",))}
    assert {
        "02-clean-architecture-hexagonal",
        "03-ddd-domain-modeling",
        "10-refactoring-strangler",
    } <= ids
    assert "07-event-driven-architecture" not in ids


def test_select_extra_forces_in_a_profiled_rule() -> None:
    catalog = RuleCatalog()
    ids = {rule.id for rule in catalog.select(set(), extra=("07-event-driven-architecture",))}
    assert "07-event-driven-architecture" in ids


def test_select_excluded_wins_over_profile() -> None:
    catalog = RuleCatalog()
    ids = {
        rule.id
        for rule in catalog.select(
            set(), profiles=("architecture",), excluded=("02-clean-architecture-hexagonal",)
        )
    }
    assert "02-clean-architecture-hexagonal" not in ids


def test_check_profiles_rejects_unknown() -> None:
    catalog = RuleCatalog()
    with pytest.raises(ValueError, match="Unknown profile.*bogus.*Available: api, architecture"):
        catalog.check_profiles(("bogus",))


def _write_catalog(tmp_path: object, manifest: dict) -> None:  # type: ignore[type-arg]
    root = tmp_path / "catalog"  # type: ignore[operator]
    root.mkdir()
    rule_dir = root / "1-core"
    rule_dir.mkdir()
    (rule_dir / "rule.md").write_text("# Rule\n")
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def test_schema_version_mismatch_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    root = _write_catalog(
        tmp_path,
        {
            "schema_version": SCHEMA_VERSION - 1,
            "profiles": {},
            "rules": [],
        },
    )
    with pytest.raises(ValueError, match="schema_version"):
        RuleCatalog(catalog_root=root)


def test_rule_with_undeclared_profile_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    root = _write_catalog(
        tmp_path,
        {
            "schema_version": SCHEMA_VERSION,
            "profiles": {},
            "rules": [
                {
                    "id": "rule",
                    "category": "1-core",
                    "file": "1-core/rule.md",
                    "description": "x",
                    "profile": "bogus",
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="unknown profile"):
        RuleCatalog(catalog_root=root)
