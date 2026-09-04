from __future__ import annotations

import json
from pathlib import Path

from ai_governance.telemetry.cost_monitor import CostMonitor
from ai_governance.telemetry.prices import PriceCatalog


def test_price_catalog_fallback_and_models() -> None:
    pin, pout = PriceCatalog.get_price("claude-sonnet-4-6")
    assert pin == 3.0
    assert pout == 15.0

    pin_unknown, pout_unknown = PriceCatalog.get_price("unknown-experimental-model")
    assert pin_unknown == 2.0
    assert pout_unknown == 10.0


def test_scan_transcripts(tmp_path: Path) -> None:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir(parents=True)
    jsonl_file = project_dir / "session.jsonl"

    sample_entry = {
        "timestamp": "2026-09-04T12:00:00Z",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 10_000,
                "output_tokens": 2_000,
                "cache_read_input_tokens": 5_000,
                "cache_creation_input_tokens": 1_000,
            },
        },
    }
    jsonl_file.write_text(json.dumps(sample_entry) + "\n", encoding="utf-8")

    monitor = CostMonitor(projects_dir=tmp_path)
    res = monitor.scan_transcripts()

    assert res["total_tokens"] == 18_000
    assert res["total_cost_usd"] > 0
    assert "2026-09-04" in res["by_day"]
