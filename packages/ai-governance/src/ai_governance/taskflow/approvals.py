"""Human approvals given in the chat and recorded by the agent.

An approval is bound to an action, a target and the current ``code_stamp``; it expires
when the code changes. Risky actions need a reinforced confirmation: the consequence that
was shown, and a reply that names the action and the target. A generic "ok"/"dale" never
approves them. Production actions are checked against the configured production risk window.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .._config_core import ConfigError
from ..settings import effective
from .models import JsonDict, now_iso

ACTIONS: tuple[str, ...] = (
    "plan",
    "contract",
    "work",
    "ticket",
    "push",
    "pr",
    "comment",
    "slack",
    "staging",
    "workflow",
    "review",
    "restaging",
    "deploy",
    "prod",
    "migration",
    "infra",
    "permissions",
    "delete",
)
# Checked without the code stamp: they never expire when the code changes.
STAMP_FREE_ACTIONS = frozenset({"plan", "workflow"})
# Words (accent-free, lowercase prefixes) the reply must contain to name a risky action.
RISKY_ACTIONS: dict[str, tuple[str, ...]] = {
    "deploy": ("deploy", "despleg", "desplieg"),
    "prod": ("produc", "prod"),
    "migration": ("migra",),
    "infra": ("infra",),
    "permissions": ("permis",),
    "delete": ("borr", "elimin", "delet", "remov"),
    "restaging": ("staging",),
}
# Production window: cutoff hours read from configuration (risk_window.*).
PRODUCTION_ACTIONS = frozenset({"deploy", "prod", "migration", "infra", "permissions"})
FRIDAY = 4
GENERIC_REPLIES = frozenset(
    {
        "ok",
        "okay",
        "dale",
        "si",
        "yes",
        "y",
        "listo",
        "adelante",
        "aprobado",
        "go",
        "va",
        "de una",
        "perfecto",
        "hacelo",
        "go ahead",
        "approved",
        "sure",
        "sip",
        "ok dale",
    }
)


class ApprovalError(ValueError):
    pass


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", plain).strip()


def is_generic(reply: str) -> bool:
    return re.sub(r"[^a-z ]", "", normalize(reply)).strip() in GENERIC_REPLIES


def _validate_hour(hour: object, key: str = "cutoff hour") -> int:
    if not isinstance(hour, int) or isinstance(hour, bool) or not (0 <= hour <= 23):
        raise ConfigError(f"Invalid value for {key}: {hour!r} (must be an hour between 0 and 23)")
    return hour


def production_window_cutoffs(root: Path | None = None) -> tuple[int, int]:
    """Cutoff hours for Monday-Thursday and Friday from configuration."""
    values = effective(root)
    cutoff = values["risk_window.cutoff_hour"].value
    friday_cutoff = values["risk_window.friday_cutoff_hour"].value
    return _validate_hour(cutoff, "risk_window.cutoff_hour"), _validate_hour(
        friday_cutoff, "risk_window.friday_cutoff_hour"
    )


def outside_production_window(
    moment: datetime,
    cutoff_hour: int | None = None,
    friday_cutoff_hour: int | None = None,
    root: Path | None = None,
) -> bool:
    if moment.weekday() > FRIDAY:
        return True
    if cutoff_hour is None or friday_cutoff_hour is None:
        cfg_cutoff, cfg_friday = production_window_cutoffs(root)
        if cutoff_hour is None:
            cutoff_hour = cfg_cutoff
        if friday_cutoff_hour is None:
            friday_cutoff_hour = cfg_friday
    last = (
        _validate_hour(friday_cutoff_hour, "risk_window.friday_cutoff_hour")
        if moment.weekday() == FRIDAY
        else _validate_hour(cutoff_hour, "risk_window.cutoff_hour")
    )
    return moment.hour >= last


def request_tag(request: ApprovalRequest) -> str:
    """The exact tag the question carries (``taskflow ask`` prints it)."""
    return (
        f"[approval {request.task_id} · {request.action} · {request.target} · {request.reference}]"
    )


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    target: str
    user_reply: str
    consequence: str = ""
    actor: str = "user"
    task_id: str = ""
    reference: str = ""


@dataclass(frozen=True)
class ApprovalContext:
    stamp_key: str
    moment: datetime
    previous: list[JsonDict] | None = None


def current_moment() -> datetime:
    """Current local datetime (indirection keeps ``approvals.datetime`` patches effective)."""
    return datetime.now()


def build_approval(request: ApprovalRequest, context: ApprovalContext) -> JsonDict:
    """Validate a chat approval and return the record to store, or raise ``ApprovalError``."""
    risky = _check_request(request)
    if request.action in PRODUCTION_ACTIONS:
        cutoff, friday_cutoff = production_window_cutoffs()
        if outside_production_window(context.moment, cutoff, friday_cutoff):
            raise ApprovalError(
                f"Outside the production window (never after {cutoff:02d}:00, nor Friday after {friday_cutoff:02d}:00): "
                "prepare it now and run it on the next working day."
            )
    return {
        "action": request.action,
        "target": request.target,
        "user_reply": request.user_reply,
        "consequence": request.consequence,
        "actor": request.actor,
        "risky": risky,
        "reference": request.reference,
        "verified": "declared",
        "stamp": context.stamp_key,
        "at": now_iso(),
    }


def _check_request(request: ApprovalRequest) -> bool:
    """Reject malformed requests; returns whether the action is risky."""
    if request.action not in ACTIONS:
        raise ApprovalError(f"Unknown action '{request.action}'. Use one of: {', '.join(ACTIONS)}")
    if not request.user_reply.strip() or not request.target.strip():
        raise ApprovalError("An approval needs --target and the user's exact reply (--user-reply)")
    risky = request.action in RISKY_ACTIONS
    if risky:
        _check_reinforced(request)
    return risky


def _check_reinforced(request: ApprovalRequest) -> None:
    if not request.consequence.strip():
        raise ApprovalError(
            f"'{request.action}' is risky: show the user the concrete consequence first "
            "(e.g. 'if it goes wrong it may wipe the production database') and pass it as --consequence"
        )
    reply = normalize(request.user_reply)
    if is_generic(request.user_reply):
        raise ApprovalError(
            f"'{request.user_reply}' is a generic reply: a risky action needs the user to name "
            "the action and the target (e.g. 'I confirm the deploy of <service> to production')"
        )
    if not any(word in reply for word in RISKY_ACTIONS[request.action]):
        raise ApprovalError(f"The user's reply does not name the action '{request.action}'")
    if normalize(request.target) not in reply:
        raise ApprovalError(f"The user's reply does not name the target '{request.target}'")


def valid_approval(
    approvals: list[JsonDict], action: str, stamp_key: str, target: str = ""
) -> JsonDict | None:
    """Latest approval for ``action`` (and ``target``, when given) still bound to the current
    code; an empty ``stamp_key`` accepts any code. ``None`` if expired."""
    for approval in reversed(approvals):
        if approval.get("action") != action or (target and approval.get("target") != target):
            continue
        return approval if not stamp_key or approval.get("stamp") == stamp_key else None
    return None
