"""
prices.py — Anthropic model pricing table and LiteLLM feed updater.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
FALLBACK_PRICE = (2.0, 10.0)


class PriceCatalog:
    @classmethod
    def get_price(cls, model_name: str, cache_path: Path | None = None) -> tuple[float, float]:
        clean_name = model_name.lower().strip()
        if cache_path and cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if clean_name in data:
                    item = data[clean_name]
                    return float(item.get("input_cost_per_million", 2.0)), float(
                        item.get("output_cost_per_million", 10.0)
                    )
            except Exception:
                pass

        for k, v in DEFAULT_PRICES.items():
            if k in clean_name:
                return v
        return FALLBACK_PRICE
