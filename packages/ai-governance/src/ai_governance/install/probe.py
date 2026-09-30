"""``ai-governance probe`` — verify on this machine what an agent really loads and fires.

Docs for Codex and Antigravity hooks/rules are not fully confirmed, so hooks for
those agents are only installed after a probe proves they work:

1. ``ai-governance probe --agent X`` builds a throwaway project with unique canary
   tokens in every candidate instructions location and recording hooks.
2. Open the agent there and send the printed prompt.
3. ``ai-governance probe --agent X --verify --seen <canaries the agent listed>``
   stores the verified capabilities; ``install --scope user`` then uses them.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..paths import state_dir
from . import content

EVENTS = ("PreToolUse", "PostToolUse", "Stop")
PROMPT = (
    "Read sample.probe, run the shell command `echo probe`, then ask the `probe-scout` "
    "subagent to read sample.probe and repeat its reply. Finally list every token that starts "
    "with CANARY- that appears in your instructions, rules or the subagent reply. "
    "Reply only with the list."
)
SCOUT_CANARY = "CANARY-SCOUT"
SCOUT_BODY = f"Start every reply with {SCOUT_CANARY}. Read-only: never modify files.\n"
# The real install writes each rule once in .agents/rules with front matter for every agent;
# Claude reads it through a symlink in .claude/rules. The probe checks both behaviours.
DUAL_RULE_PATH = ".agents/rules/probe-dual.md"
DUAL_RULE = (
    '---\npaths:\n  - "**/*.probe"\ntrigger: glob\nglobs: "**/*.probe"\n'
    'description: "probe"\n---\n- {token}\n'
)


def _canaries(agent: str) -> dict[str, tuple[str, str]]:
    """canary -> (relative path, file content)."""
    agents_md = ("AGENTS.md", "# Probe\n- CANARY-AGENTS-MD\n")
    if agent == "claude":
        return {
            "CANARY-AGENTS-MD": agents_md,
            "CANARY-CLAUDE-PATHS": (
                ".claude/rules/probe-paths.md",
                '---\npaths:\n  - "**/*.probe"\n---\n- CANARY-CLAUDE-PATHS\n',
            ),
            "CANARY-CLAUDE-LINK": (DUAL_RULE_PATH, DUAL_RULE.format(token="CANARY-CLAUDE-LINK")),
            SCOUT_CANARY: (
                ".claude/agents/probe-scout.md",
                "---\nname: probe-scout\ndescription: Probe subagent\ntools: Read\n"
                "model: sonnet\neffort: medium\n---\n" + SCOUT_BODY,
            ),
        }
    if agent == "codex":
        return {
            "CANARY-AGENTS-MD": agents_md,
            "CANARY-CODEX-NESTED": ("sub/AGENTS.md", "- CANARY-CODEX-NESTED\n"),
            SCOUT_CANARY: (
                ".codex/agents/probe-scout.toml",
                'name = "probe-scout"\ndescription = "Probe subagent"\nmodel = "terra"\n'
                'model_reasoning_effort = "medium"\nsandbox_mode = "read-only"\n'
                f'developer_instructions = """\n{SCOUT_BODY}"""\n',
            ),
        }
    return {
        "CANARY-AGENTS-MD": agents_md,
        "CANARY-AG-ALWAYS": (
            ".agents/rules/probe-always.md",
            "---\ntrigger: always_on\n---\n- CANARY-AG-ALWAYS\n",
        ),
        "CANARY-AG-GLOB": (
            ".agents/rules/probe-glob.md",
            '---\ntrigger: glob\nglobs: "**/*.probe"\n---\n- CANARY-AG-GLOB\n',
        ),
        "CANARY-AG-DUAL": (DUAL_RULE_PATH, DUAL_RULE.format(token="CANARY-AG-DUAL")),
        SCOUT_CANARY: (
            ".agents/agents/probe-scout.md",
            "---\nname: probe-scout\ndescription: Probe subagent\n"
            + content.ANTIGRAVITY_SCOUT_SETTINGS
            + "hooks:\n  - probe-scout-hooks.json\n---\n"
            + SCOUT_BODY,
        ),
    }


def hooks_file(agent: str, root: Path) -> Path | None:
    return {
        "codex": root / ".codex" / "hooks.json",
        "antigravity": root / ".agents" / "hooks.json",
    }.get(agent)


def records_dir(agent: str) -> Path:
    return state_dir() / "probe" / agent


def results_path() -> Path:
    return state_dir() / "probe" / "verified.json"


def build(agent: str, root: Path | None = None) -> Path:
    root = root or Path(tempfile.mkdtemp(prefix=f"ai-governance-probe-{agent}-"))
    for relative, text in _canaries(agent).values():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "sample.probe").write_text("probe sample\n", encoding="utf-8")
    if agent == "claude":
        link = root / ".claude" / "rules" / "probe-dual.md"
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to("../../" + DUAL_RULE_PATH)
    target = hooks_file(agent, root)
    if target is not None:
        hooks = {
            event: [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"ai-governance probe-record {agent} {event}",
                        }
                    ]
                }
            ]
            for event in EVENTS
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"hooks": hooks}, indent=2) + "\n", encoding="utf-8")
    if agent == "antigravity":
        # Alternative channel: hooks declared in a custom agent's front matter (2.17.0).
        agent_hooks = {
            event: [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"ai-governance probe-record {agent} agent-{event}",
                        }
                    ]
                }
            ]
            for event in EVENTS
        }
        (root / ".agents" / "agents" / "probe-scout-hooks.json").write_text(
            json.dumps({"hooks": agent_hooks}, indent=2) + "\n", encoding="utf-8"
        )
    records = records_dir(agent)
    if records.exists():
        for old in records.glob("*.json"):
            old.unlink()
    return root


def record(agent: str, event: str) -> int:
    """Hook command used by the probe: stores the payload shape, prints nothing."""
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    shape: dict[str, Any] = {"keys": sorted(payload) if isinstance(payload, dict) else []}
    if isinstance(payload, dict):
        shape["has_command"] = bool((payload.get("tool_input") or {}).get("command"))
        response = payload.get("tool_response")
        shape["tool_response"] = type(response).__name__
        if isinstance(response, dict):
            shape["tool_response_keys"] = sorted(response)
    directory = records_dir(agent)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{event}.json").write_text(json.dumps(shape), encoding="utf-8")
    return 0


def verify(agent: str, seen: list[str]) -> dict[str, Any]:
    fired = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(records_dir(agent).glob("*.json"))
    }
    expected = set(_canaries(agent))
    result = {
        "canaries_seen": sorted(set(seen) & expected),
        "canaries_missing": sorted(expected - set(seen)),
        "hooks_fired": fired,
        "shell_hooks_verified": bool(
            fired.get("PreToolUse", {}).get("has_command")
            and fired.get("PostToolUse", {}).get("has_command")
        ),
        "scout_verified": SCOUT_CANARY in seen,
        "agent_frontmatter_hooks_fired": sorted(
            name.removeprefix("agent-") for name in fired if name.startswith("agent-")
        ),
    }
    path = results_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[agent] = result
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def shell_hooks_verified(agent: str) -> bool:
    path = results_path()
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    return bool(data.get(agent, {}).get("shell_hooks_verified"))
