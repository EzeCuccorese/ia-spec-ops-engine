import json

import pytest
from ai_governance.rules.catalog import SCHEMA_VERSION, RuleCatalog


def test_catalog_loads_all_rules_with_metadata() -> None:
    catalog = RuleCatalog()
    assert len(catalog.rules) == 35
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


def test_code_design_rules_need_a_language_stack() -> None:
    catalog = RuleCatalog()
    code_rules = {"01-clean-code-solid", "11-self-documenting-code"}
    assert code_rules <= {r.id for r in catalog.select({"python"})}
    assert not code_rules & {r.id for r in catalog.select({"docker", "github-actions"})}


def test_code_design_rules_leave_numeric_limits_to_ws_design() -> None:
    import re

    catalog = RuleCatalog()
    for rule_id in ("01-clean-code-solid", "11-self-documenting-code"):
        content = catalog.get(rule_id).content
        assert not re.search(r"(arity|nesting|parameters?|lines?)\s*(≤|<=)", content, re.I)


def test_user_rules_cover_every_language_and_tool_rules() -> None:
    catalog = RuleCatalog()
    user_ids = {rule.id for rule in catalog.user_rules()}
    stacks = {rule.id for rule in catalog.rules if rule.category == "2-stacks"}
    assert stacks <= user_ids
    assert "api-design" in user_ids
    tool_rules = {
        "circleci",
        "13-atlassian",
        "14-taskflow",
        "15-tool-confidentiality",
        "16-git-branch-ownership",
    }
    assert tool_rules <= user_ids
    assert {rule.id for rule in catalog.user_rules() if rule.always_on} == tool_rules
    # language-level rules remain path-scoped
    language_rules = [r for r in catalog.user_rules() if r.id not in tool_rules]
    assert not any(rule.always_on for rule in language_rules)


def test_git_branch_and_circleci_rule_content_semantics() -> None:
    catalog = RuleCatalog()

    # git-branch-ownership: exact required semantics
    branch_rule = catalog.get("16-git-branch-ownership")
    assert branch_rule is not None
    assert branch_rule.user_scope is True
    assert branch_rule.always_on is True
    content = branch_rule.content
    assert "user created it or asked the agent to create it" in content
    assert "never pushes, force-pushes, rebases, resets, deletes or commits" in content
    assert "exact action and branch" in content
    assert "user's explicit authorization" in content
    assert "one authorization covers one action on one branch" in content.lower()
    assert "unclear ownership means not the user's" in content.lower()

    # circleci: reads free, writes need approval, deploy hold prohibited, tokens named by variable
    circleci = catalog.get("circleci")
    assert circleci is not None
    assert circleci.user_scope is True
    assert circleci.always_on is True
    c_content = circleci.content
    assert "reads" in c_content.lower() and "free" in c_content.lower()
    assert "POST" in c_content and "DELETE" in c_content
    assert "approval" in c_content.lower()
    assert "deploy hold" in c_content.lower()
    assert "CIRCLE_TOKEN" in c_content and "CIRCLE_TOKEN_RW" in c_content


def test_atlassian_taskflow_and_confidentiality_rule_content_semantics() -> None:
    catalog = RuleCatalog()

    # atlassian: CLI commands, $ATLASSIAN_URL, reads free, writes need approval
    atlassian = catalog.get("13-atlassian")
    assert atlassian is not None
    assert atlassian.user_scope is True
    assert atlassian.always_on is True
    a_content = atlassian.content
    assert "ai-governance jira" in a_content and "ai-governance confluence" in a_content
    assert "$ATLASSIAN_URL" in a_content
    assert "free" in a_content.lower()
    assert "approval" in a_content.lower()

    # taskflow: task registry and tracking
    taskflow = catalog.get("14-taskflow")
    assert taskflow is not None
    assert taskflow.user_scope is True
    assert taskflow.always_on is True
    t_content = taskflow.content
    assert "ai-governance taskflow" in t_content
    assert "here" in t_content and "status" in t_content and "new" in t_content and "bind" in t_content

    # tool-confidentiality: engine tooling never mentioned
    conf = catalog.get("15-tool-confidentiality")
    assert conf is not None
    assert conf.user_scope is True
    assert conf.always_on is True
    conf_content = conf.content
    assert "never mentioned in tickets, PRs, commits, reviews or chat tools" in conf_content


def test_every_language_rule_states_how_to_validate_input() -> None:
    for rule in RuleCatalog().rules:
        if rule.category == "2-stacks":
            assert "valid" in rule.content.lower(), rule.id
