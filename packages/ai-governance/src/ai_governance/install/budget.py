"""Fixed context cost per agent: bytes loaded every session, before any file is touched."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..frontmatter import _FRONTMATTER_RE
from .engine import END, START, Ledger
from .installer import COMPLETIONS_OWNER, SCHEDULE_OWNER, SCRIPTS_OWNER

BYTES_PER_TOKEN = 4
# Fixed-context warning thresholds: leaves headroom under Antigravity's 20k-token rules
# cap (accounting for non-English tokenization and workspace AGENTS.md / user_global).
ALWAYS_ON_WARN_BYTES = 40_000
SKILL_CATALOG_WARN_BYTES = 16_000
SKILL_COUNT_WARN = 35


def _always_loaded(path: Path, text: str, agent: str = "") -> bool:
    """Path-scoped rules load only for matching files; everything else is fixed cost."""
    if path.suffix != ".md":
        return False
    posix = path.as_posix()
    if "/ai-governance/always/" in posix:
        return True
    if posix.endswith("/ai-governance/company/index.md"):
        return True
    if "/rules/" in posix:
        match = _FRONTMATTER_RE.match(text)
        header = match.group(1) if match else ""
        if agent == "claude":
            return "paths:" not in header
        if agent == "antigravity":
            return "trigger: glob" not in header
        return "paths:" not in header and "trigger: glob" not in header
    return False


def _block(text: str) -> str:
    if START in text and END in text:
        return text.split(START, 1)[1].split(END, 1)[0]
    return ""


def _user_content(text: str) -> str:
    if START in text and END in text:
        before = text.split(START, 1)[0]
        after = text.split(END, 1)[1]
        return (before + after).strip()
    return text.strip()


def _entry_costs(kind: str, path: Path, agent: str = "") -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    if kind == "block":
        agent_bytes = len(_block(text).encode("utf-8"))
        user_text = _user_content(text) if path.name == "AGENTS.md" else ""
        user_bytes = len(user_text.encode("utf-8")) if user_text else 0
        return agent_bytes, user_bytes
    if _always_loaded(path, text, agent):
        return len(text.encode("utf-8")), 0
    return 0, 0


_IGNORED_OWNERS = frozenset({SCRIPTS_OWNER, COMPLETIONS_OWNER, SCHEDULE_OWNER})


def _file_targets(ledger: Ledger) -> set[Path]:
    return {
        ledger.resolve(entry["path"]).resolve()
        for entry in ledger.entries
        if entry["kind"] == "file" and entry["agent"] not in _IGNORED_OWNERS
    }


def _should_count(entry: dict[str, str], path: Path, file_targets: set[Path]) -> bool:
    if entry["agent"] in _IGNORED_OWNERS or entry["kind"] == "hooks" or not path.is_file():
        return False
    return not (entry["kind"] == "link" and path.resolve() in file_targets)


def fixed_cost(ledger: Ledger) -> dict[str, int]:
    """Bytes per owner (each agent, ``project`` = shared, ``user_custom`` = user custom) loaded at session start."""
    totals: dict[str, int] = {}
    file_targets = _file_targets(ledger)
    for entry in ledger.entries:
        path = ledger.resolve(entry["path"])
        if not _should_count(entry, path, file_targets):
            continue
        agent_bytes, user_bytes = _entry_costs(entry["kind"], path, entry["agent"])
        if user_bytes:
            totals["user_custom"] = totals.get("user_custom", 0) + user_bytes
        totals[entry["agent"]] = totals.get(entry["agent"], 0) + agent_bytes
    return totals


def _skill_frontmatter_bytes(skill_dir: Path) -> int:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return 0
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    match = _FRONTMATTER_RE.match(text)
    return len(match.group(1).encode("utf-8")) if match else 0


def skill_catalog_cost(ledger: Ledger) -> dict[str, tuple[int, int]]:
    """Returns ``{agent: (skill_count, frontmatter_bytes)}`` for managed skills in ``ledger``."""
    counts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    for entry in ledger.entries:
        if entry.get("kind") != "dir":
            continue
        agent = str(entry.get("agent", ""))
        if agent in _IGNORED_OWNERS:
            continue
        path = ledger.resolve(str(entry["path"]))
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            continue
        counts[agent] = counts.get(agent, 0) + 1
        sizes[agent] = sizes.get(agent, 0) + _skill_frontmatter_bytes(path)
    return {agent: (counts[agent], sizes[agent]) for agent in counts}


def _always_on_warnings(
    ledger: Ledger, selected: set[str] | None, limit: int
) -> list[tuple[str, str]]:
    warnings: list[tuple[str, str]] = []
    limit_tokens = limit // BYTES_PER_TOKEN
    for agent, size in sorted(fixed_cost(ledger).items()):
        if agent == "user_custom" or (selected is not None and agent not in selected):
            continue
        if size > limit:
            tokens = size // BYTES_PER_TOKEN
            warnings.append(
                (
                    agent,
                    f"always-on rules for {agent} total {size} bytes (~{tokens} tokens), "
                    f"above the {limit}-byte (~{limit_tokens}-token) safe budget; "
                    "move reference/domain rules into skills/ and run `ai-governance budget`",
                )
            )
    return warnings


def _skill_catalog_warnings(
    ledger: Ledger, selected: set[str] | None, count_limit: int, bytes_limit: int
) -> list[tuple[str, str]]:
    warnings: list[tuple[str, str]] = []
    for agent, (count, fm_bytes) in sorted(skill_catalog_cost(ledger).items()):
        if selected is not None and agent not in selected:
            continue
        if count > count_limit or fm_bytes > bytes_limit:
            warnings.append(
                (
                    agent,
                    f"installed skills catalog for {agent} has {count} skills "
                    f"({fm_bytes} bytes of frontmatter metadata; thresholds: "
                    f"{count_limit} skills / {bytes_limit} bytes); "
                    "prune or consolidate overlapping skills",
                )
            )
    return warnings


def budget_warnings(
    ledger: Ledger,
    *,
    agents: Iterable[str] | None = None,
    always_on_limit: int = ALWAYS_ON_WARN_BYTES,
    skill_catalog_limit: int = SKILL_CATALOG_WARN_BYTES,
    skill_count_limit: int = SKILL_COUNT_WARN,
) -> list[tuple[str, str]]:
    """Returns ``(agent, warning)`` pairs when fixed always-on rules or skill metadata grow too large."""
    selected = set(agents) if agents is not None else None
    return [
        *_always_on_warnings(ledger, selected, always_on_limit),
        *_skill_catalog_warnings(ledger, selected, skill_count_limit, skill_catalog_limit),
    ]
