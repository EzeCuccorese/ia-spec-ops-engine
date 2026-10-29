"""Human approvals given in the chat and recorded by the agent.

An approval is bound to an action, a target and the current ``code_stamp``; it expires
when the code changes. Risky actions need a reinforced confirmation: the consequence that
was shown, and a reply that names the action and the target. A generic "ok"/"dale" never
approves them. When a Claude Code transcript exists for the working directory, the reply
must appear verbatim in a real user message there; risky actions without that proof are
refused.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
    "tdd-skip",
    "workflow",
    "review",
    "restaging",
    "deploy",
    "prod",
    "migration",
    "infra",
    "permissions",
    "delete",
    "policy-downgrade",
)
# Words (accent-free, lowercase prefixes) the reply must contain to name a risky action.
RISKY_ACTIONS: dict[str, tuple[str, ...]] = {
    "deploy": ("deploy", "despleg", "desplieg"),
    "prod": ("produc", "prod"),
    "migration": ("migra",),
    "infra": ("infra",),
    "permissions": ("permis",),
    "delete": ("borr", "elimin", "delet", "remov"),
    "policy-downgrade": ("politic", "policy", "riesgo", "risk"),
    "restaging": ("staging",),
}
# Production window (user rule): never after 16:00, and never on Friday after 13:00.
PRODUCTION_ACTIONS = frozenset({"deploy", "prod", "migration", "infra", "permissions"})
LAST_HOUR = 16
FRIDAY_LAST_HOUR = 13
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
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
# Only the user's last few messages can approve: an old "ok" never approves new work.
RECENT_USER_MESSAGES = 3


class ApprovalError(ValueError):
    pass


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", plain).strip()


def is_generic(reply: str) -> bool:
    return re.sub(r"[^a-z ]", "", normalize(reply)).strip() in GENERIC_REPLIES


def outside_production_window(moment: datetime) -> bool:
    if moment.weekday() > FRIDAY:
        return True
    last = FRIDAY_LAST_HOUR if moment.weekday() == FRIDAY else LAST_HOUR
    return moment.hour >= last


def _messages(transcript: Path) -> list[tuple[str, str]]:
    """(role, text) of what the user typed and what the assistant wrote, in order.

    Tool results also arrive as ``user`` entries: only typed text blocks count, and
    harness-injected text (``<...>`` blocks, meta entries) is skipped.
    """
    messages: list[tuple[str, str]] = []
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        role = entry.get("type")
        if role not in ("user", "assistant") or entry.get("isMeta"):
            continue
        texts = _text_blocks((entry.get("message") or {}).get("content"))
        messages += [(role, t) for t in texts if t and not t.lstrip().startswith("<")]
    return messages


def _text_blocks(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [
        c.get("text", "")
        for c in content or []  # type: ignore[attr-defined]
        if isinstance(c, dict) and c.get("type") == "text"
    ]


def in_claude_session() -> bool:
    return bool(os.environ.get("CLAUDECODE") or os.environ.get(SESSION_ENV))


def current_transcript(root: Path = CLAUDE_PROJECTS) -> Path | None:
    """Transcript of the Claude Code session running this command (``CLAUDE_CODE_SESSION_ID``).

    Without a session id there is no transcript: another session's history never proves
    anything here."""
    session = os.environ.get(SESSION_ENV, "")
    return next(iter(sorted(root.glob(f"*/{session}.jsonl"))), None) if session else None


def request_tag(request: ApprovalRequest) -> str:
    """The exact tag the question must carry (``taskflow ask`` prints it), so a reply can
    only approve what was asked: this task, action and target, on this plan or code."""
    return (
        f"[approval {request.task_id} · {request.action} · {request.target} · {request.reference}]"
    )


def find_proof(request: ApprovalRequest, transcript: Path, risky: bool) -> str:
    """``<transcript>#<message>`` of a recent user message that is exactly the reply and
    answers the assistant message carrying this request's tag (and, for risky actions,
    showing the consequence); else ``""``."""
    wanted = normalize(request.user_reply)
    messages = _messages(transcript)
    users = [i for i, (role, _text) in enumerate(messages) if role == "user"]
    for index in reversed(users[-RECENT_USER_MESSAGES:]):  # an answer to what was just asked
        if normalize(messages[index][1]) == wanted and _answers_request(
            messages, index, request, risky
        ):
            return f"{transcript}#{index}"
    return ""


def _answers_request(
    messages: list[tuple[str, str]], index: int, request: ApprovalRequest, risky: bool
) -> bool:
    asked = [t for r, t in messages[:index] if r == "assistant"][-1:]
    if not asked or request_tag(request) not in asked[0]:  # exact: ids are case-sensitive
        return False
    return not risky or normalize(request.consequence) in normalize(asked[0])


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    target: str
    user_reply: str
    consequence: str = ""
    actor: str = "user"
    task_id: str = ""
    reference: str = ""  # plan-r<validation round> for plans, else the code stamp


@dataclass(frozen=True)
class ApprovalContext:
    stamp_key: str
    moment: datetime
    previous: list[JsonDict] | None = None
    transcripts_root: Path = CLAUDE_PROJECTS


def build_approval(request: ApprovalRequest, context: ApprovalContext) -> JsonDict:
    """Validate a chat approval and return the record to store, or raise ``ApprovalError``.

    Inside a Claude Code session every approval must match a whole user message of that
    session (and risky ones must follow the consequence shown); a proof is used once.
    Without a transcript (other agents) ordinary approvals are recorded as ``declared``
    and risky ones are refused.
    """
    risky = _check_request(request)
    proof = _require_proof(request, context.transcripts_root, risky)
    if proof and any(a.get("proof") == proof for a in context.previous or []):
        raise ApprovalError("That user message already approved something: ask the user again")
    if request.action in PRODUCTION_ACTIONS and outside_production_window(context.moment):
        raise ApprovalError(
            "Outside the production window (never after 16:00, nor Friday after 13:00): "
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
        "verified": "transcript" if proof else "declared",
        "proof": proof,
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


def _require_proof(request: ApprovalRequest, transcripts_root: Path, risky: bool) -> str:
    transcript = current_transcript(transcripts_root)
    proof = find_proof(request, transcript, risky) if transcript else ""
    if transcript and not proof:
        raise ApprovalError(
            f"The reply is not a recent message the user typed in this session answering a "
            f"question that carries {request_tag(request)} (print it with `taskflow ask`)"
            + (" with the consequence shown" if risky else "")
            + ": ask first (naming action and target), then pass the user's whole reply verbatim"
        )
    if in_claude_session() and not proof:
        raise ApprovalError("Inside Claude Code an approval needs this session's transcript")
    if risky and not proof:
        raise ApprovalError(
            "A risky action is approved only from a Claude Code session with the user's own words"
        )
    return proof


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
            "the action and the target (e.g. 'confirmo deploy de <service> a producción')"
        )
    if not any(word in reply for word in RISKY_ACTIONS[request.action]):
        raise ApprovalError(f"The user's reply does not name the action '{request.action}'")
    if normalize(request.target) not in reply:
        raise ApprovalError(f"The user's reply does not name the target '{request.target}'")


def valid_approval(
    approvals: list[JsonDict], action: str, stamp_key: str, target: str = ""
) -> JsonDict | None:
    """Latest approval for ``action`` (and ``target``, when given) still bound to the current
    code; an empty ``stamp_key`` accepts any code (e.g. the plan). ``None`` if expired."""
    for approval in reversed(approvals):
        if approval.get("action") != action or (target and approval.get("target") != target):
            continue
        return approval if not stamp_key or approval.get("stamp") == stamp_key else None
    return None
