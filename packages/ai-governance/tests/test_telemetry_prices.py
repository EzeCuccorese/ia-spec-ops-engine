"""Coverage tests for ai_governance.telemetry.prices."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ai_governance.telemetry import prices as prices_module
from ai_governance.telemetry.prices import FALLBACK_PRICE, PriceCatalog, _fetch_json


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_fetch_json_returns_parsed_object(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"model": {"input_cost_per_token": 1}}).encode("utf-8")

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr(prices_module.urllib.request, "urlopen", fake_urlopen)
    result = _fetch_json("https://example.test/feed", 5.0)
    assert result == {"model": {"input_cost_per_token": 1}}


def test_fetch_json_rejects_non_dict_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps([1, 2, 3]).encode("utf-8")

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr(prices_module.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ValueError, match="must be a JSON object"):
        _fetch_json("https://example.test/feed", 5.0)


def test_load_cache_none_path_returns_empty() -> None:
    assert PriceCatalog.load_cache(None) == {}


def test_load_cache_missing_file_returns_empty(tmp_path: Path) -> None:
    assert PriceCatalog.load_cache(tmp_path / "missing.json") == {}


def test_load_cache_non_dict_source_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"prices": [1, 2]}), encoding="utf-8")
    assert PriceCatalog.load_cache(path) == {}


def test_load_cache_skips_non_dict_items_and_non_numeric_prices(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps(
            {
                "prices": {
                    "model-a": "not-a-dict",
                    "model-b": {"input": "bad", "output": 10.0},
                    "model-c": {"input": 2.0, "output": 10.0},
                }
            }
        ),
        encoding="utf-8",
    )
    result = PriceCatalog.load_cache(path)
    assert result == {"model-c": (2.0, 10.0)}


def test_load_cache_handles_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    path.write_text("not json", encoding="utf-8")
    assert PriceCatalog.load_cache(path) == {}


def test_get_price_exact_match() -> None:
    assert PriceCatalog.get_price("claude-sonnet-5") == (2.0, 10.0)


def test_get_price_prefix_match() -> None:
    price = PriceCatalog.get_price("claude-sonnet-5-20260101")
    assert price == (2.0, 10.0)


def test_get_price_fallback_for_unknown_model() -> None:
    assert PriceCatalog.get_price("totally-unknown-model") == FALLBACK_PRICE


def test_cache_age_days_computes_from_fetched_at(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    fetched = datetime.now(UTC) - timedelta(days=3)
    path.write_text(json.dumps({"fetched_at": fetched.isoformat()}), encoding="utf-8")
    assert PriceCatalog.cache_age_days(path) == 3


def test_cache_age_days_handles_z_suffix(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    fetched = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)
    stamp = fetched.isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps({"fetched_at": stamp}), encoding="utf-8")
    assert PriceCatalog.cache_age_days(path) == 1


def test_cache_age_days_handles_naive_datetime(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    fetched = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
    path.write_text(json.dumps({"fetched_at": fetched.isoformat()}), encoding="utf-8")
    assert PriceCatalog.cache_age_days(path) == 2


def test_cache_age_days_missing_file_returns_none(tmp_path: Path) -> None:
    assert PriceCatalog.cache_age_days(tmp_path / "missing.json") is None


def test_cache_age_days_missing_fetched_at_key_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    assert PriceCatalog.cache_age_days(path) is None


def test_refresh_cache_skips_non_anthropic_and_non_dict_entries(tmp_path: Path) -> None:
    target = tmp_path / "prices.json"
    feed: dict[str, Any] = {
        "claude-a": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 0.000001,
            "output_cost_per_token": 0.000005,
        },
        "not-a-dict": "oops",
        "other-provider": {
            "litellm_provider": "openai",
            "input_cost_per_token": 0.000001,
            "output_cost_per_token": 0.000001,
        },
    }
    document = PriceCatalog.refresh_cache(target, "https://x", fetcher=lambda _u, _t: feed)
    assert list(document["prices"].keys()) == ["claude-a"]


def test_refresh_cache_skips_non_numeric_costs(tmp_path: Path) -> None:
    target = tmp_path / "prices.json"
    feed: dict[str, Any] = {
        "claude-a": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": "bad",
            "output_cost_per_token": 0.000005,
        },
        "claude-b": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 0.000001,
            "output_cost_per_token": 0.000005,
        },
    }
    document = PriceCatalog.refresh_cache(target, "https://x", fetcher=lambda _u, _t: feed)
    assert list(document["prices"].keys()) == ["claude-b"]


def test_refresh_cache_skips_negative_costs(tmp_path: Path) -> None:
    target = tmp_path / "prices.json"
    feed: dict[str, Any] = {
        "claude-a": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": -1,
            "output_cost_per_token": 0.000005,
        },
        "claude-b": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 0.000001,
            "output_cost_per_token": 0.000005,
        },
    }
    document = PriceCatalog.refresh_cache(target, "https://x", fetcher=lambda _u, _t: feed)
    assert list(document["prices"].keys()) == ["claude-b"]


def test_refresh_cache_cleans_up_temp_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "prices.json"
    feed: dict[str, Any] = {
        "claude-a": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 0.000001,
            "output_cost_per_token": 0.000005,
        },
    }

    def boom(self: Path, _dest: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        PriceCatalog.refresh_cache(target, "https://x", fetcher=lambda _u, _t: feed)
    assert list(tmp_path.iterdir()) == []


def test_get_price_prefers_the_longest_prefix() -> None:
    assert PriceCatalog.get_price("claude-opus-5-5-20261001") == (4.0, 20.0)
    assert PriceCatalog.get_price("claude-opus-5-20260101") == (5.0, 25.0)


def test_cache_multipliers_defaults_and_known_models(tmp_path: Path) -> None:
    assert PriceCatalog.cache_multipliers("claude-sonnet-5") == (0.1, 1.25, 2.0)
    assert PriceCatalog.cache_multipliers("claude-opus-5-5")[0] == pytest.approx(0.05)
    assert PriceCatalog.cache_multipliers("claude-opus-5-5", tmp_path / "missing.json")[0] == (
        pytest.approx(0.05)
    )


def test_cache_multipliers_come_from_the_feed_cache(tmp_path: Path) -> None:
    cache = tmp_path / "prices.json"
    cache.write_text(
        json.dumps(
            {
                "prices": {
                    "claude-x": {
                        "input": 4.0,
                        "output": 20.0,
                        "cache_read": 0.2,
                        "cache_write_1h": 8.0,
                    },
                    "claude-zero": {"input": 0, "output": 1.0, "cache_read": 0.5},
                    "bad": "entry",
                }
            }
        )
    )
    assert PriceCatalog.cache_multipliers("claude-x", cache) == pytest.approx((0.05, 1.25, 2.0))
    assert PriceCatalog.cache_multipliers("claude-zero", cache) == (0.1, 1.25, 2.0)
    cache.write_text("not json")
    assert PriceCatalog.cache_multipliers("claude-x", cache) == (0.1, 1.25, 2.0)
    cache.write_text(json.dumps({"prices": ["list"]}))
    assert PriceCatalog.cache_multipliers("claude-x", cache) == (0.1, 1.25, 2.0)


def test_refresh_cache_keeps_cache_rates(tmp_path: Path) -> None:
    feed = {
        "claude-x": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 4e-6,
            "output_cost_per_token": 2e-5,
            "cache_read_input_token_cost": 2e-7,
            "cache_creation_input_token_cost": 5e-6,
        }
    }
    document = PriceCatalog.refresh_cache(tmp_path / "c.json", fetcher=lambda url, timeout: feed)
    assert document["prices"]["claude-x"] == {
        "input": 4.0,
        "output": 20.0,
        "cache_read": 0.2,
        "cache_write_5m": 5.0,
    }
