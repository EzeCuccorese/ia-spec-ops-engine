"""Per-agent capability matrix: where each supported agent loads each artifact.

Single source of truth for the installer, ``doctor`` and the README table
(``ai-governance agents``). Only the agents the user explicitly
selects are ever touched.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..corporate import CorporateRule
from ..rules.catalog import RuleDefinition
from . import content

MARKER = "ai-governance"
HOOK_COMMAND_PREFIX = "ai-governance hook"


@dataclass(frozen=True)
class FileArtifact:
    """A whole file owned by ai-governance."""

    path: Path
    text: str


@dataclass(frozen=True)
class BlockArtifact:
    """A marker-delimited block inside a file that may hold user content.

    ``comment`` is the line-comment prefix used for the markers (``None`` = HTML
    comments for Markdown). ``prepend`` puts the block first, e.g. TOML top-level keys
    that must precede any table.
    """

    path: Path
    body: str
    comment: str | None = None
    prepend: bool = False
    conflict: str | None = None  # regex; if it matches the file, the block is skipped

    @property
    def markers(self) -> tuple[str, str]:
        if self.comment:
            return f"{self.comment} {MARKER}:start", f"{self.comment} {MARKER}:end"
        return f"<!-- {MARKER}:start -->", f"<!-- {MARKER}:end -->"


@dataclass(frozen=True)
class HookEntry:
    event: str
    matcher: str | None
    command: str


@dataclass(frozen=True)
class HooksArtifact:
    """Hook entries merged into an agent's JSON settings file."""

    path: Path
    entries: tuple[HookEntry, ...]


@dataclass(frozen=True)
class LinkArtifact:
    """A relative symlink owned by ai-governance (e.g. Claude rules -> .agents/rules)."""

    path: Path
    target: str


Artifact = FileArtifact | BlockArtifact | HooksArtifact | LinkArtifact

# Single source of truth for project rules: every agent reads them from here.
RULES_DIR = Path(".agents") / "rules"


def canonical_rule_path(root: Path, rule: RuleDefinition) -> Path:
    return root / RULES_DIR / f"ai-governance-{rule.id}.md"


def render_canonical_rule(rule: RuleDefinition) -> str:
    """One file, front matter understood by every agent: Claude reads `paths:`,
    Antigravity reads `trigger`/`globs`/`description`; unknown keys are ignored."""
    if rule.always_on:
        header = "---\ntrigger: always_on\n"
    else:
        header = (
            f"---\npaths:\n{_yaml_list(rule.globs)}\n"
            f"trigger: glob\nglobs: {json.dumps(','.join(rule.globs))}\n"
        )
    return header + f"description: {json.dumps(rule.description)}\n---\n" + _rule_body(rule)


def _yaml_list(values: tuple[str, ...]) -> str:
    return "\n".join(f"  - {json.dumps(value)}" for value in values)


def _rule_body(rule: RuleDefinition) -> str:
    return f"{content.GENERATED_NOTE}\n{rule.content.strip()}\n"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    global_instructions: str
    global_hooks: str
    project_rules: str
    project_rules_mechanism: str
    scout: str
    skills: str

    # -- global (user) scope -------------------------------------------------
    def global_artifacts(self) -> list[Artifact]:
        raise NotImplementedError

    def corporate_artifacts(self, rules: list[CorporateRule]) -> list[Artifact]:
        """Always-on company rules; empty when the agent has no per-file global rules."""
        return []

    # -- project scope -------------------------------------------------------
    def project_artifacts(
        self, root: Path, rules: list[RuleDefinition], *, gate: bool = False
    ) -> list[Artifact]:
        """Agent-specific extras; the rules themselves live once in `.agents/rules`."""
        return []

    def _verified_hooks(self, path: Path, *entries: HookEntry) -> list[Artifact]:
        """Hooks whose wire format is only trusted after `ai-governance probe` verified it."""
        from .probe import shell_hooks_verified

        return [HooksArtifact(path, entries)] if shell_hooks_verified(self.id) else []


class ClaudeSpec(AgentSpec):
    def global_artifacts(self) -> list[Artifact]:
        home = Path.home() / ".claude"
        command = f"{HOOK_COMMAND_PREFIX} claude"
        return [
            FileArtifact(home / "rules" / "ai-governance.md", content.GLOBAL_INSTRUCTIONS),
            FileArtifact(
                home / "agents" / "scout.md",
                "---\n"
                "name: scout\n"
                f"description: {content.SCOUT_DESCRIPTION}\n"
                "tools: Read, Grep, Glob, WebSearch, WebFetch\n"
                "model: sonnet\n"
                "effort: medium\n"
                "omitClaudeMd: true\n"
                "---\n" + content.SCOUT_INSTRUCTIONS,
            ),
            *skill_artifacts(home / "skills"),
            HooksArtifact(
                home / "settings.json",
                (
                    HookEntry("PreToolUse", "Bash", f"{command} pre-tool-use"),
                    HookEntry("PostToolUse", "Bash", f"{command} post-tool-use"),
                    HookEntry("Stop", None, f"{command} stop"),
                    HookEntry("SessionStart", None, f"{command} session-start"),
                    HookEntry("SessionEnd", None, f"{command} session-end"),
                ),
            ),
        ]

    def corporate_artifacts(self, rules: list[CorporateRule]) -> list[Artifact]:
        home = Path.home() / ".claude" / "rules"
        return [
            LinkArtifact(home / f"ai-governance-{r.pack}-{r.name}.md", str(r.path)) for r in rules
        ]

    def project_artifacts(
        self, root: Path, rules: list[RuleDefinition], *, gate: bool = False
    ) -> list[Artifact]:
        artifacts: list[Artifact] = [
            LinkArtifact(
                root / ".claude" / "rules" / f"ai-governance-{rule.id}.md",
                f"../../{RULES_DIR.as_posix()}/ai-governance-{rule.id}.md",
            )
            for rule in rules
        ]
        if gate:
            artifacts.append(
                HooksArtifact(
                    root / ".claude" / "settings.json",
                    (HookEntry("Stop", None, f"{HOOK_COMMAND_PREFIX} claude stop-gate"),),
                )
            )
        return artifacts


class CodexSpec(AgentSpec):
    def global_artifacts(self) -> list[Artifact]:
        home = codex_home()
        return [
            BlockArtifact(home / "AGENTS.md", content.GLOBAL_INSTRUCTIONS),
            FileArtifact(
                home / "agents" / "scout.toml",
                'name = "scout"\n'
                f"description = {json.dumps(content.SCOUT_DESCRIPTION)}\n"
                'model = "terra"\n'
                'model_reasoning_effort = "medium"\n'
                'sandbox_mode = "read-only"\n'
                f'developer_instructions = """\n{content.SCOUT_INSTRUCTIONS}"""\n',
            ),
            BlockArtifact(
                home / "config.toml",
                'agents.default_subagent_model = "terra"\n'
                'agents.default_subagent_reasoning_effort = "medium"\n',
                comment="#",
                prepend=True,
                conflict=r"^\s*\[agents\]|^\s*agents\.default_subagent_",
            ),
            *skill_artifacts(Path.home() / ".agents" / "skills"),
            *self._verified_hooks(
                home / "hooks.json",
                HookEntry("PostToolUse", None, f"{HOOK_COMMAND_PREFIX} codex post-tool-use"),
            ),
        ]


class AntigravitySpec(AgentSpec):
    def corporate_artifacts(self, rules: list[CorporateRule]) -> list[Artifact]:
        home = Path.home() / ".gemini" / "config" / "rules"
        return [
            LinkArtifact(home / f"ai-governance-{r.pack}-{r.name}.md", str(r.path)) for r in rules
        ]

    def global_artifacts(self) -> list[Artifact]:
        home = Path.home() / ".gemini"
        return [
            FileArtifact(
                home / "config" / "rules" / "ai-governance.md",
                "---\ntrigger: always_on\n---\n" + content.GLOBAL_INSTRUCTIONS,
            ),
            FileArtifact(
                home / "config" / "agents" / "scout.md",
                "---\n"
                "name: scout\n"
                f"description: {content.SCOUT_DESCRIPTION}\n"
                + content.ANTIGRAVITY_SCOUT_SETTINGS
                + "---\n"
                + content.SCOUT_INSTRUCTIONS,
            ),
            *skill_artifacts(home / "config" / "skills"),
            *self._verified_hooks(
                home / "antigravity-cli" / "hooks.json",
                HookEntry("PreToolUse", None, f"{HOOK_COMMAND_PREFIX} antigravity pre-tool-use"),
            ),
        ]


def skill_artifacts(skills_dir: Path) -> list[Artifact]:
    """One ``<name>/SKILL.md`` per bundled skill, in the agent's skills directory."""
    return [
        FileArtifact(skills_dir / name / "SKILL.md", body) for name, body in content.SKILLS.items()
    ]


AGENTS: dict[str, AgentSpec] = {
    "claude": ClaudeSpec(
        id="claude",
        name="Claude Code",
        global_instructions="~/.claude/rules/ai-governance.md",
        global_hooks="~/.claude/settings.json (Pre/PostToolUse Bash, Stop, SessionStart/End)",
        project_rules=".claude/rules/ai-governance-<id>.md -> symlink to .agents/rules",
        project_rules_mechanism="native `paths:` frontmatter (loaded per file)",
        scout="~/.claude/agents/scout.md (sonnet, effort medium)",
        skills="~/.claude/skills/{progress,test-audit}/SKILL.md",
    ),
    "codex": CodexSpec(
        id="codex",
        name="OpenAI Codex",
        global_instructions="$CODEX_HOME/AGENTS.md (marker block)",
        global_hooks="$CODEX_HOME/hooks.json PostToolUse condensing (after `probe` verifies)",
        project_rules=".agents/rules/ai-governance-<id>.md (shared)",
        project_rules_mechanism="injected on edit by a PreToolUse hook (planned)",
        scout="$CODEX_HOME/agents/scout.toml (terra, effort medium, read-only) + config.toml default subagent model terra",
        skills="~/.agents/skills/{progress,test-audit}/SKILL.md",
    ),
    "antigravity": AntigravitySpec(
        id="antigravity",
        name="Google Antigravity 2",
        global_instructions="~/.gemini/config/rules/ai-governance.md (`trigger: always_on`)",
        global_hooks="~/.gemini/antigravity-cli/hooks.json PreToolUse: raw noisy commands -> `ws run` (after `probe`)",
        project_rules=".agents/rules/ai-governance-<id>.md (single source)",
        project_rules_mechanism="`trigger: glob` activation (loaded per file; 20k-token rules budget)",
        scout="~/.gemini/config/agents/scout.md (model flash, read-only tools, no commands)",
        skills="~/.gemini/config/skills/{progress,test-audit}/SKILL.md",
    ),
}


def resolve_agents(names: list[str]) -> list[AgentSpec]:
    unknown = [name for name in names if name not in AGENTS]
    if unknown:
        raise ValueError(
            f"Unknown agent(s): {', '.join(unknown)}. Choose from: {', '.join(AGENTS)}"
        )
    return [AGENTS[name] for name in dict.fromkeys(names)]


def capability_table() -> str:
    """Markdown table generated from the matrix (embedded in the README)."""
    rows = [
        ("Global instructions", "global_instructions"),
        ("Global hooks", "global_hooks"),
        ("Scout subagent", "scout"),
        ("Skills", "skills"),
        ("Project rules", "project_rules"),
        ("Rule loading", "project_rules_mechanism"),
    ]
    specs = list(AGENTS.values())
    lines = [
        "| | " + " | ".join(spec.name for spec in specs) + " |",
        "|---|" + "---|" * len(specs),
    ]
    for label, attr in rows:
        cells = " | ".join(getattr(spec, attr) for spec in specs)
        lines.append(f"| {label} | {cells} |")
    return "\n".join(lines)
