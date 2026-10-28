"""Risk by path: rules matching the changed files add judges, checks and re-staging."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from .config import FlowConfig, RiskRule


@dataclass(frozen=True)
class RiskAssessment:
    rules: tuple[RiskRule, ...]
    judges: tuple[str, ...]
    checks: tuple[str, ...]
    restaging: bool

    @property
    def level(self) -> str:
        if self.restaging:
            return "high"
        return "medium" if self.rules else "low"


def assess(config: FlowConfig, paths: list[str]) -> RiskAssessment:
    """Every matching rule counts: obligations accumulate, none cancels another."""
    matched = tuple(
        rule
        for rule in config.risk_rules
        if any(fnmatch(path, pattern) for path in paths for pattern in rule.paths)
    )
    base_judges = [str(j.get("focus")) for j in config.judges]
    judges = dict.fromkeys([*base_judges, *(f for rule in matched for f in rule.judges)])
    checks = dict.fromkeys([*config.checks, *(c for rule in matched for c in rule.checks)])
    return RiskAssessment(
        rules=matched,
        judges=tuple(judges),
        checks=tuple(checks),
        restaging=any(rule.restaging for rule in matched),
    )
