"""Validated local Anthropic price catalog with explicit remote refresh."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
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
DEFAULT_FEED_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "specops-telemetry/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Price feed must be a JSON object")
    return value


class PriceCatalog:
    @staticmethod
    def load_cache(cache_path: Path | None) -> dict[str, tuple[float, float]]:
        if cache_path is None or not cache_path.exists():
            return {}
        try:
            document = json.loads(cache_path.read_text(encoding="utf-8"))
            source = document.get("prices", document)
            if not isinstance(source, dict):
                return {}
            prices: dict[str, tuple[float, float]] = {}
            for model, item in source.items():
                if not isinstance(item, dict):
                    continue
                input_price = item.get("input", item.get("input_cost_per_million"))
                output_price = item.get("output", item.get("output_cost_per_million"))
                if isinstance(input_price, (int, float)) and isinstance(output_price, (int, float)):
                    prices[str(model).lower()] = (float(input_price), float(output_price))
            return prices
        except (OSError, ValueError, TypeError):
            return {}

    @classmethod
    def get_price(cls, model_name: str, cache_path: Path | None = None) -> tuple[float, float]:
        clean_name = model_name.lower().strip()
        prices = dict(DEFAULT_PRICES)
        prices.update(cls.load_cache(cache_path))
        if clean_name in prices:
            return prices[clean_name]
        for known, price in prices.items():
            if clean_name.startswith(known):
                return price
        return FALLBACK_PRICE

    @staticmethod
    def cache_age_days(cache_path: Path) -> int | None:
        try:
            document = json.loads(cache_path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(str(document["fetched_at"]).replace("Z", "+00:00"))
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=UTC)
            return (datetime.now(UTC) - fetched.astimezone(UTC)).days
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @classmethod
    def refresh_cache(
        cls,
        cache_path: Path,
        url: str = DEFAULT_FEED_URL,
        *,
        timeout: float = 10.0,
        fetcher: Callable[[str, float], dict[str, Any]] = _fetch_json,
    ) -> dict[str, Any]:
        feed = fetcher(url, timeout)
        prices: dict[str, dict[str, float]] = {}
        for model, metadata in feed.items():
            if not isinstance(metadata, dict) or metadata.get("litellm_provider") != "anthropic":
                continue
            input_cost = metadata.get("input_cost_per_token")
            output_cost = metadata.get("output_cost_per_token")
            if not isinstance(input_cost, (int, float)) or not isinstance(
                output_cost, (int, float)
            ):
                continue
            if input_cost < 0 or output_cost < 0:
                continue
            prices[str(model).lower()] = {
                "input": round(float(input_cost) * 1_000_000, 8),
                "output": round(float(output_cost) * 1_000_000, 8),
            }
        if not prices:
            raise ValueError("Price feed contains no direct Anthropic models")
        document = {
            "schema_version": 1,
            "fetched_at": datetime.now(UTC).isoformat(),
            "source_url": url,
            "prices": prices,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=cache_path.parent, delete=False
            ) as handle:
                json.dump(document, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            temp_path.replace(cache_path)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
        return document
