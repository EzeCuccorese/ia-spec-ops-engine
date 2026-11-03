"""The status of a pull request, computed by code from what GitHub reported. Pure.

No model and no free text is involved: the blockers are a fixed vocabulary derived from a
validated ``Snapshot``. A PR is never ``ready`` unless every dimension is known and fine, so
missing or stale data always shows up as a blocker or as ``stale``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .snapshot import Snapshot

STALE_HOURS = 6
SYNC_HINT = "stale (taskflow pr sync)"
_CI = {"failed": "ci-failed", "running": "ci-running", "unknown": "unknown-ci"}
_REVIEW = {
    "changes": "changes-requested",
    "required": "needs-approval",
    "unknown": "unknown-review",
}
_MERGEABLE = {"conflicting": "conflict", "unknown": "unknown-mergeable"}
_BUCKETS = (
    "draft",
    "ci-failed",
    "ci-running",
    "changes-requested",
    "needs-approval",
    "conflict",
    "open-threads",
    "waits-on-base",
    "unknown",
    "sync-error",
    "not-synced",
)


@dataclass(frozen=True)
class Evaluation:
    """One PR as shown to a person: state, blockers, readiness and how old the data is."""

    state: str
    blockers: tuple[str, ...]
    ready: bool
    stale: bool
    age_s: int | None
    error: str = ""
    synced_at: str = ""
    snapshot: Snapshot | None = None


def _threads(snapshot: Snapshot) -> list[str]:
    count = snapshot.threads_open
    if count is None:
        return ["unknown-threads"]
    if count == 0:
        return []
    return [f"{count}{'+' if snapshot.threads_incomplete else ''}-open-threads"]


def _parent(snapshot: Snapshot) -> list[str]:
    kind, number = snapshot.parent.kind, snapshot.parent.number
    return {
        "open": [f"waits-on-#{number}"],
        "closed": [f"parent-closed-#{number}"],
        "ambiguous": ["ambiguous-parent"],
        "unknown": ["unknown-parent"],
    }.get(kind, [])


def classify(snapshot: Snapshot) -> tuple[str, ...]:
    """The ordered blockers of a snapshot; a merged or closed PR has none (state is shown)."""
    if snapshot.state != "OPEN":
        return ()
    known = [
        *_ci_and_review(snapshot),
        *_conflict(snapshot),
        *_threads(snapshot),
        *_parent(snapshot),
    ]
    first = [b for b in known if not b.startswith("unknown")]
    unknown = [b for b in known if b.startswith("unknown")]
    return tuple(["draft"] * snapshot.is_draft + first + unknown)


def _ci_and_review(snapshot: Snapshot) -> list[str]:
    return [*([_CI[snapshot.ci]] if snapshot.ci in _CI else []), *_review_blockers(snapshot)]


def _review_blockers(snapshot: Snapshot) -> list[str]:
    return [_REVIEW[snapshot.review]] if snapshot.review in _REVIEW else []


def _conflict(snapshot: Snapshot) -> list[str]:
    return [_MERGEABLE[snapshot.mergeable]] if snapshot.mergeable in _MERGEABLE else []


def parse_time(value: object, now: datetime) -> datetime | None:
    """A UTC timestamp, or None when it is absent, unparsable or in the future."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return moment if moment <= now else None


def evaluate(entry: Mapping[str, Any] | None, now: datetime | None = None) -> Evaluation:
    """Turn a cache entry (or its absence) into what to show; ``now`` is injectable."""
    now = now or datetime.now(UTC)
    synced = parse_time(entry.get("synced_at"), now) if entry else None
    if entry is None or synced is None:
        return Evaluation("unknown", ("not-synced",), False, False, None)
    stamp, age = synced.isoformat(timespec="seconds"), int((now - synced).total_seconds())
    snapshot = Snapshot.from_dict(entry.get("snapshot"))
    if snapshot is None:
        failed = bool(entry.get("error"))
        unsynced: tuple[str, ...] = ("sync-error",) if failed else ("not-synced",)
        return Evaluation(
            "unknown", unsynced, False, False, age, str(entry.get("error", "")), stamp
        )
    stale = snapshot.state != "MERGED" and age > STALE_HOURS * 3600  # merged is final
    blockers = classify(snapshot)
    ready = snapshot.state == "OPEN" and not blockers and not stale
    return Evaluation(snapshot.state.lower(), blockers, ready, stale, age, "", stamp, snapshot)


def bucket(blockers: Sequence[str]) -> str:
    """The summary bucket of a PR: its first blocker, grouped."""
    first = blockers[0] if blockers else ""
    if first.endswith("-open-threads"):
        return "open-threads"
    if first.startswith(("waits-on", "parent-closed", "ambiguous-parent")):
        return "waits-on-base"
    return "unknown" if first.startswith("unknown") else first


def _bucket_counts(evaluations: Sequence[Evaluation]) -> Counter[str]:
    """How many open PRs fall in each summary bucket (finished PRs are not counted)."""
    counts: Counter[str] = Counter()
    for item in evaluations:
        if item.state not in ("merged", "closed"):
            counts["ready" if item.ready else bucket(item.blockers) or "stale"] += 1
    return counts


def summarize(evaluations: Sequence[Evaluation]) -> str:
    """``PRs: 30 (4 merged) · 2 needs-approval · 1 ci-failed · stale (taskflow pr sync)``."""
    if not evaluations:
        return ""
    states = Counter(e.state for e in evaluations)
    done = [f"{states[s]} {s}" for s in ("merged", "closed") if states[s]]
    head = f"PRs: {len(evaluations)}" + (f" ({', '.join(done)})" if done else "")
    order = ("ready", *_BUCKETS, "stale")
    ranked = sorted(_bucket_counts(evaluations).items(), key=lambda i: (-i[1], order.index(i[0])))
    parts = [f"{n} {name}" for name, n in ranked]
    if any(e.stale for e in evaluations):
        parts.append(SYNC_HINT)
    return " · ".join([head, *parts])
