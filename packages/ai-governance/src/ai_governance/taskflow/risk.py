"""Risk by path: rules matching the changed files add judges, checks and re-staging."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from .config import FlowConfig, RiskRule
from .models import JsonDict


@dataclass(frozen=True)
class RiskAssessment:
    rules: tuple[RiskRule, ...]
    judges: tuple[str, ...]
    checks: tuple[str, ...]
    restaging: bool
    # Frozen decision type per focus: while a repo is missing these win over the live config,
    # in both directions (a live namesake can neither add nor remove a human decision).
    human: tuple[str, ...] = ()
    engine: tuple[str, ...] = ()

    @property
    def level(self) -> str:
        if self.restaging:
            return "high"
        return "medium" if self.rules else "low"


def _touches(rule: RiskRule, paths: list[str]) -> bool:
    return any(fnmatch(path, pattern) for path in paths for pattern in rule.paths)


def assess(config: FlowConfig, paths: list[str]) -> RiskAssessment:
    """Every matching rule counts: obligations accumulate, none cancels another."""
    matched = tuple(rule for rule in config.risk_rules if _touches(rule, paths))
    base_judges = [str(j.get("focus")) for j in config.judges]
    judges = dict.fromkeys([*base_judges, *(f for rule in matched for f in rule.judges)])
    checks = dict.fromkeys([*config.checks, *(c for rule in matched for c in rule.checks)])
    return RiskAssessment(
        rules=matched,
        judges=tuple(judges),
        checks=tuple(checks),
        restaging=any(rule.restaging for rule in matched),
    )


def merge(first: RiskAssessment, second: RiskAssessment) -> RiskAssessment:
    """Union of two assessments: obligations only accumulate, none is ever dropped."""
    rules = {rule.name: rule for rule in (*first.rules, *second.rules)}
    return RiskAssessment(
        rules=tuple(rules.values()),
        judges=tuple(dict.fromkeys([*first.judges, *second.judges])),
        checks=tuple(dict.fromkeys([*first.checks, *second.checks])),
        restaging=first.restaging or second.restaging,
        # ``second`` is the frozen side: its type for a focus replaces the other side's.
        human=tuple(
            dict.fromkeys([*second.human, *(f for f in first.human if f not in second.engine)])
        ),
        engine=tuple(
            dict.fromkeys([*second.engine, *(f for f in first.engine if f not in second.human)])
        ),
    )


def freeze(risk: RiskAssessment, config: FlowConfig) -> JsonDict:
    """What eligibility needs, complete and independent of any path list or config file:
    the rules that matched, every required focus (and which of them a human decides),
    the extra checks and the restaging demand."""
    human = [f for f in risk.judges if decided_by_human(risk, config, f)]
    return {
        "rules": [
            {
                "name": r.name,
                "paths": list(r.paths),
                "judges": list(r.judges),
                "checks": list(r.checks),
                "restaging": r.restaging,
            }
            for r in risk.rules
        ],
        "judges": list(risk.judges),
        "human": human,
        "engine": [f for f in risk.judges if f not in human],
        "checks": list(risk.checks),
        "restaging": risk.restaging,
    }


def thaw(frozen: JsonDict) -> RiskAssessment:
    rules = tuple(
        RiskRule(
            str(r["name"]),
            tuple(r.get("paths", ())),
            tuple(r.get("judges", ())),
            tuple(r.get("checks", ())),
            bool(r.get("restaging")),
        )
        for r in frozen.get("rules", [])
    )
    return RiskAssessment(
        rules=rules,
        judges=tuple(frozen.get("judges", ())),
        checks=tuple(frozen.get("checks", ())),
        restaging=bool(frozen.get("restaging")),
        human=tuple(frozen.get("human", ())),
        engine=tuple(frozen.get("engine", ())),
    )


def decided_by_human(risk: RiskAssessment, config: FlowConfig, focus: str) -> bool:
    if focus in risk.engine:
        return False
    return focus in risk.human or is_human(config, focus)


def is_human(config: FlowConfig, focus: str) -> bool:
    return any(j.get("focus") == focus and j.get("agent") == "human" for j in config.judges)


def _rule_from(name: str, rule: JsonDict) -> RiskRule:
    return RiskRule(
        name,
        tuple(rule.get("paths", ())),
        tuple(rule.get("judges", ())),
        tuple(rule.get("checks", ())),
        bool(rule.get("restaging")),
    )


def _union(first: RiskRule, second: RiskRule) -> RiskRule:
    return RiskRule(
        first.name,
        tuple(dict.fromkeys([*first.paths, *second.paths])),
        tuple(dict.fromkeys([*first.judges, *second.judges])),
        tuple(dict.fromkeys([*first.checks, *second.checks])),
        first.restaging or second.restaging,
    )


def legacy_obligations(accepted: JsonDict, config: FlowConfig) -> RiskAssessment:
    """State stamped before obligations were frozen carries no paths: assume the worst, that
    every rule of the accepted policy and of the live config matched, and that a rule seen in
    both versions carries the union of their controls. Never more permissive than a task
    whose repositories are all present."""
    rules: dict[str, RiskRule] = {}
    versions = [
        *config.risk_rules,
        *(_rule_from(n, r) for n, r in accepted.get("rules", {}).items()),
    ]
    for rule in versions:
        rules[rule.name] = _union(rules[rule.name], rule) if rule.name in rules else rule
    judges = [*accepted.get("judges", []), *(f for r in rules.values() for f in r.judges)]
    checks = [*accepted.get("checks", []), *(c for r in rules.values() for c in r.checks)]
    return RiskAssessment(
        rules=tuple(rules.values()),
        judges=tuple(dict.fromkeys(judges)),
        checks=tuple(dict.fromkeys(checks)),
        restaging=any(r.restaging for r in rules.values()),
        # The accepted policy stores focus names only, so the type is unknown: take the
        # strictest reading (an engine verdict), never the live definition of a namesake.
        engine=tuple(dict.fromkeys(judges)),
    )
