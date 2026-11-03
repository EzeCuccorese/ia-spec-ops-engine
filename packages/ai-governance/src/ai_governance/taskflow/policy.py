"""Part of ``cli`` (split out, no behavior change)."""

from __future__ import annotations

from .config import FlowConfig, summarize
from .config import _rule_reductions as _rule_reductions
from .config import policy_reductions as policy_reductions
from .models import JsonDict


def policy_summary(config: FlowConfig) -> JsonDict:
    """The controls a task accepted, rule by rule; weakening any of them later is a
    reduction that needs the user's D3 ``policy-downgrade`` approval."""
    return {
        **summarize(config.judges, config.checks, config.risk_rules),
        # Reductions by trusted repositories that the user already approved for this task.
        "acknowledged_repo_reductions": list(config.repo_reductions),
    }
