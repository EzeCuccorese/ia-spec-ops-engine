"""Validated local Anthropic price catalog with explicit remote refresh."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import astuple, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-5-5": (0.1, 0.5),
    "claude-haiku-4-5": (1.0, 5.0),
}
FALLBACK_PRICE = (2.0, 10.0)
# Cache rates relative to the input price: (read, 5-minute write, 1-hour write).
DEFAULT_CACHE_MULTIPLIERS = (0.1, 1.25, 2.0)
# Models whose cache read is not 10% of input, for when the feed cache is missing.
DEFAULT_CACHE_READ: dict[str, float] = {
    "claude-fable-5-1": 0.025,
    "claude-mythos-5-1": 0.025,
    "claude-opus-5-5": 0.05,
    "claude-sonnet-5-5": 0.05,
}
# Long-prompt tier: above `threshold` prompt tokens every rate switches to the tier's.
DEFAULT_TIERS: dict[str, tuple[int, tuple[float, float]]] = {
    "claude-haiku-5-5": (100_000, (0.5, 2.5)),
}
# Fast mode (usage.speed == "fast") multiplies every rate; the feed carries it as
# provider_specific_entry.fast.
DEFAULT_FAST_MULTIPLIER = 2.0
CACHE_FIELDS = (
    ("cache_read", "cache_read_input_token_cost"),
    ("cache_write_5m", "cache_creation_input_token_cost"),
    ("cache_write_1h", "cache_creation_input_token_cost_above_1hr"),
)
TIER_INPUT_FIELD = re.compile(r"^input_cost_per_token_above_(\d+)k_tokens$")


@dataclass(frozen=True)
class Rates:
    """USD per million tokens for one request."""

    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float

    def scaled(self, factor: float) -> Rates:
        return Rates(*(value * factor for value in astuple(self)))


FEED_TIMEOUT = 10.0
DEFAULT_FEED_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "ai-governance-telemetry/1"})
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

    @staticmethod
    def _match(clean_name: str, table: dict[str, Any]) -> str | None:
        if clean_name in table:
            return clean_name
        # Longest prefix first: "claude-opus-5-5-x" must not resolve to "claude-opus-5".
        for known in sorted(table, key=len, reverse=True):
            if clean_name.startswith(known):
                return known
        return None

    @classmethod
    def get_price(cls, model_name: str, cache_path: Path | None = None) -> tuple[float, float]:
        prices = dict(DEFAULT_PRICES)
        prices.update(cls.load_cache(cache_path))
        known = cls._match(model_name.lower().strip(), prices)
        return prices[known] if known else FALLBACK_PRICE

    @classmethod
    def cache_multipliers(
        cls, model_name: str, cache_path: Path | None = None
    ) -> tuple[float, float, float]:
        """(read, 5m write, 1h write) relative to input: feed cache, then known defaults."""
        clean_name = model_name.lower().strip()
        read, write_5m, write_1h = DEFAULT_CACHE_MULTIPLIERS
        known = cls._match(clean_name, DEFAULT_CACHE_READ)
        if known:
            read = DEFAULT_CACHE_READ[known]
        entries = cls._cache_entries(cache_path)
        known = cls._match(clean_name, entries)
        if not known:
            return read, write_5m, write_1h
        return _feed_multipliers(entries[known], (read, write_5m, write_1h))

    @classmethod
    def rates(
        cls,
        model_name: str,
        cache_path: Path | None = None,
        *,
        prompt_tokens: int = 0,
        fast: bool = False,
    ) -> Rates:
        """Per-request rates: base or long-prompt tier, scaled by the fast-mode multiplier."""
        clean_name = model_name.lower().strip()
        input_price, output_price = cls.get_price(clean_name, cache_path)
        multipliers = cls.cache_multipliers(clean_name, cache_path)
        entries = cls._cache_entries(cache_path)
        entry = entries.get(cls._match(clean_name, entries) or "", {})
        tier = _tier(entry) or _default_tier(cls._match(clean_name, DEFAULT_TIERS))
        if tier and prompt_tokens > tier[0]:
            input_price, output_price = tier[1]
            multipliers = _feed_multipliers(tier[2], multipliers) if tier[2] else multipliers
        read, write_5m, write_1h = multipliers
        rates = Rates(
            input_price,
            output_price,
            input_price * read,
            input_price * write_5m,
            input_price * write_1h,
        )
        if not fast:
            return rates
        factor = entry.get("fast")
        return rates.scaled(
            factor if isinstance(factor, (int, float)) and factor > 0 else DEFAULT_FAST_MULTIPLIER
        )

    @staticmethod
    def _cache_entries(cache_path: Path | None) -> dict[str, dict[str, Any]]:
        if cache_path is None or not cache_path.exists():
            return {}
        try:
            document = json.loads(cache_path.read_text(encoding="utf-8"))
            source = document.get("prices", document)
            if not isinstance(source, dict):
                return {}
            return {str(k).lower(): v for k, v in source.items() if isinstance(v, dict)}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

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
        fetcher: Callable[[str, float], dict[str, Any]] = _fetch_json,
    ) -> dict[str, Any]:
        prices = _direct_anthropic_prices(fetcher(url, FEED_TIMEOUT))
        if not prices:
            raise ValueError("Price feed contains no direct Anthropic models")
        document = {
            "schema_version": 1,
            "fetched_at": datetime.now(UTC).isoformat(),
            "source_url": url,
            "prices": prices,
        }
        _atomic_write_json(cache_path, document)
        return document


def _feed_multipliers(
    item: dict[str, Any], defaults: tuple[float, float, float]
) -> tuple[float, float, float]:
    input_price = item.get("input")
    if not isinstance(input_price, (int, float)) or input_price <= 0:
        return defaults
    values = list(defaults)
    for index, (name, _) in enumerate(CACHE_FIELDS):
        rate = item.get(name)
        if isinstance(rate, (int, float)) and rate > 0:
            values[index] = float(rate) / float(input_price)
    return values[0], values[1], values[2]


def _tier(entry: dict[str, Any]) -> tuple[int, tuple[float, float], dict[str, Any]] | None:
    """(threshold, (input, output), feed-style rates) of a cached long-prompt tier."""
    tier = entry.get("tier")
    if not isinstance(tier, dict):
        return None
    numbers = [tier.get(key) for key in ("threshold", "input", "output")]
    values = [float(value) for value in numbers if isinstance(value, (int, float)) and value > 0]
    if len(values) != len(numbers):
        return None
    threshold, input_price, output_price = values
    return int(threshold), (input_price, output_price), tier


def _default_tier(
    known: str | None,
) -> tuple[int, tuple[float, float], dict[str, Any]] | None:
    if known is None:
        return None
    threshold, prices = DEFAULT_TIERS[known]
    return threshold, prices, {}


def _per_million(value: Any) -> float | None:
    """Per-token feed cost as USD per million tokens; None when missing or negative."""
    if not isinstance(value, (int, float)) or value < 0:
        return None
    return round(float(value) * 1_000_000, 8)


def _feed_entry(metadata: Any) -> dict[str, Any] | None:
    if not isinstance(metadata, dict) or metadata.get("litellm_provider") != "anthropic":
        return None
    input_cost = _per_million(metadata.get("input_cost_per_token"))
    output_cost = _per_million(metadata.get("output_cost_per_token"))
    if input_cost is None or output_cost is None:
        return None
    entry: dict[str, Any] = {"input": input_cost, "output": output_cost}
    for name, feed_field in CACHE_FIELDS:
        rate = _per_million(metadata.get(feed_field))
        if rate:
            entry[name] = rate
    tier = _feed_tier(metadata)
    if tier:
        entry["tier"] = tier
    fast = _feed_fast(metadata)
    if fast:
        entry["fast"] = fast
    return entry


def _feed_fast(metadata: dict[str, Any]) -> float | None:
    """The feed's fast-mode multiplier (provider_specific_entry.fast), if any."""
    specific = metadata.get("provider_specific_entry")
    fast = specific.get("fast") if isinstance(specific, dict) else None
    return float(fast) if isinstance(fast, (int, float)) and fast > 0 else None


def _feed_tier(metadata: dict[str, Any]) -> dict[str, float] | None:
    """The feed's `*_above_<N>k_tokens` rates as {threshold, input, output, cache_*}."""
    sizes = [int(m.group(1)) for m in map(TIER_INPUT_FIELD.match, metadata) if m]
    if not sizes:
        return None
    size = min(sizes)
    suffix = f"_above_{size}k_tokens"
    input_cost = _per_million(metadata.get(f"input_cost_per_token{suffix}"))
    output_cost = _per_million(metadata.get(f"output_cost_per_token{suffix}"))
    if not input_cost or output_cost is None:
        return None
    tier: dict[str, float] = {"threshold": size * 1000, "input": input_cost, "output": output_cost}
    for name, feed_field in CACHE_FIELDS:
        field = (
            f"cache_creation_input_token_cost_above_1hr{suffix}"
            if name == "cache_write_1h"
            else f"{feed_field}{suffix}"
        )
        rate = _per_million(metadata.get(field))
        if rate:
            tier[name] = rate
    return tier


def _direct_anthropic_prices(feed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = {str(model).lower(): _feed_entry(metadata) for model, metadata in feed.items()}
    return {model: entry for model, entry in entries.items() if entry is not None}


def _atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
