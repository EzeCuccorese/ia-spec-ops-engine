"""
guard.py — Evaluates active context window size and recommends compact/clear actions.
"""

from __future__ import annotations
from typing import Any


class ContextGuard:
    DEFAULT_THRESHOLD = 120_000

    @classmethod
    def evaluate(cls, current_tokens: int, threshold: int = DEFAULT_THRESHOLD) -> dict[str, Any]:
        used_ratio = current_tokens / threshold if threshold > 0 else 0.0
        status = "normal"
        recommendation = ""

        if current_tokens >= threshold:
            status = "critical"
            recommendation = (
                "Context window limit reached. Recommend running `/compact` or saving progress and `/clear`."
            )
        elif current_tokens >= threshold * 0.6:
            status = "warning"
            recommendation = (
                "Context usage exceeds 60%. Consider pruning history if the task continues."
            )

        return {
            "tokens": current_tokens,
            "threshold": threshold,
            "ratio": used_ratio,
            "status": status,
            "recommendation": recommendation,
        }
