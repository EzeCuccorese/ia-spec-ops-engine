"""Part of ``cli`` (split out, no behavior change)."""

from __future__ import annotations

from .config import FlowConfig, summarize
from .models import JsonDict


def policy_summary(config: FlowConfig) -> JsonDict:
    """The controls a task accepted, rule by rule; weakening any of them later is a
    reduction that needs the user's D3 ``policy-downgrade`` approval."""
    return summarize(config.judges, config.checks, config.risk_rules)


def _rule_reductions(name: str, rule: JsonDict, now: JsonDict | None) -> list[str]:
    if now is None:
        return [f"rule:{name}"]
    lost = [
        f"rule:{name}:{kind}:{item}"
        for kind in ("paths", "judges", "checks")
        for item in rule.get(kind, [])
        if item not in now.get(kind, [])
    ]
    if rule.get("restaging") and not now.get("restaging"):
        lost.append(f"rule:{name}:restaging")
    return lost


def policy_reductions(baseline: JsonDict, current: JsonDict) -> list[str]:
    """Every accepted control that is gone or weaker now (adding controls is never one)."""
    lost = [
        f"{kind}:{item}"
        for kind in ("judges", "checks")
        for item in baseline.get(kind, [])
        if item not in current.get(kind, [])
    ]
    for name, rule in baseline.get("rules", {}).items():
        lost += _rule_reductions(name, rule, current.get("rules", {}).get(name))
    return sorted(lost)
