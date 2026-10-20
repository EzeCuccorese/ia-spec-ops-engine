import json
import time as time_module
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from ai_governance.telemetry.cost_monitor import CostMonitor
from ai_governance.telemetry.dates import DateParseError, parse_date, resolve_window

TODAY = date(2026, 10, 19)


@pytest.fixture
def buenos_aires(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TZ", "America/Argentina/Buenos_Aires")
    time_module.tzset()
    yield
    monkeypatch.undo()
    time_module.tzset()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5", date(2026, 10, 5)),
        ("15/10", date(2026, 10, 15)),
        ("10/15", date(2026, 10, 15)),
        ("31-12", date(2026, 12, 31)),
        ("12.31", date(2026, 12, 31)),
        ("5/10", date(2026, 10, 5)),
        ("15/10/2026", date(2026, 10, 15)),
        ("10/15/2026", date(2026, 10, 15)),
        ("15-10-26", date(2026, 10, 15)),
        ("1/10/2026", date(2026, 10, 1)),
        ("2026-10-1", date(2026, 10, 1)),
        ("2026/10/15", date(2026, 10, 15)),
        ("20261015", date(2026, 10, 15)),
    ],
)
def test_parse_date_formats(text: str, expected: date) -> None:
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize("text", ["", "abc", "31/02", "2026-19-10", "1/2/3/4", "32"])
def test_parse_date_rejects_garbage(text: str) -> None:
    with pytest.raises(DateParseError):
        parse_date(text, TODAY)


def test_window_defaults_to_month_start_until_now(buenos_aires: None) -> None:
    now = datetime(2026, 10, 19, 14, 32, tzinfo=UTC)  # 11:32 local
    window = resolve_window(None, None, now)
    start, end = window.utc
    assert start == datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    assert end == now


def test_window_is_local_days_converted_to_utc(buenos_aires: None) -> None:
    now = datetime(2026, 10, 19, 14, 32, tzinfo=UTC)
    start, end = resolve_window("1", "30", now).utc
    assert start == datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    assert end.date() == date(2026, 10, 31)  # 23:59 local on the 30th = 02:59Z on the 31st


def test_reversed_window_is_rejected(buenos_aires: None) -> None:
    with pytest.raises(DateParseError, match="reversed"):
        resolve_window("2026-10-19", "2016-10-19", datetime(2026, 10, 19, tzinfo=UTC))


def test_scan_uses_exact_instants(tmp_path: Path) -> None:
    def event(stamp: str, ident: str) -> str:
        return json.dumps(
            {
                "timestamp": stamp,
                "requestId": ident,
                "message": {
                    "id": ident,
                    "model": "claude-sonnet-4-5",
                    "usage": {"input_tokens": 1000, "output_tokens": 1000},
                },
            }
        )

    project = tmp_path / "p"
    project.mkdir()
    (project / "s.jsonl").write_text(
        "\n".join(
            [
                event("2026-10-01T02:59:00Z", "before"),
                event("2026-10-01T03:01:00Z", "inside"),
                event("2026-10-31T02:30:00Z", "late"),
                event("2026-10-31T03:30:00Z", "after"),
            ]
        ),
        encoding="utf-8",
    )
    bounds = (datetime(2026, 10, 1, 3, tzinfo=UTC), datetime(2026, 10, 31, 3, tzinfo=UTC))
    monitor = CostMonitor(projects_dir=tmp_path)
    one = monitor.scan_transcripts(instants=(bounds[0], datetime(2026, 10, 1, 3, 2, tzinfo=UTC)))[
        "total_cost_usd"
    ]
    both = monitor.scan_transcripts(instants=bounds)["total_cost_usd"]
    assert one > 0
    assert both == pytest.approx(one * 2)
