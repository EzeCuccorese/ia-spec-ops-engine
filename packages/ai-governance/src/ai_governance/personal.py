"""Personal preference packs (``~/.config/ai-governance/personal/``): always-on rules.

Personal rules live outside the repository in ``$AI_GOVERNANCE_PERSONAL_DIR`` or
``$AI_GOVERNANCE_CONFIG_DIR/personal`` (default ``~/.config/ai-governance/personal``).
Every rule present in ``<root>/rules/*.md`` is installed as a symlink for each selected agent.
"""

from __future__ import annotations

import argparse
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import check_frontmatter, ensure_frontmatter
from .output import emit_rows, emit_status
from .paths import config_dir

PERSONAL_DIR = "personal"

README_CONTENT = """# Personal Rules

Personal engineering preferences and rules live here.
Every `.md` file in this directory (except `README.md`) is symlinked into all supported AI agents (Claude, Codex, Antigravity).

## Format

Rules must include YAML front matter specifying the trigger mode:

```markdown
---
trigger: always_on
---
# Rule Title

Rule contents...
```

Supported triggers:
- `trigger: always_on`: Rule is always active in every session.
- `trigger: glob`: Rule is active when matching files are edited.
"""


def personal_root() -> Path:
    explicit = os.environ.get("AI_GOVERNANCE_PERSONAL_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return config_dir() / PERSONAL_DIR


def is_default_root() -> bool:
    return "AI_GOVERNANCE_PERSONAL_DIR" not in os.environ


def ensure_personal_dir(root: Path | None = None) -> Path:
    """Ensure ~/.config/ai-governance/personal/rules/ exists with a README."""
    rules_dir = (root or personal_root()) / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    readme = rules_dir / "README.md"
    if not readme.exists():
        readme.write_text(README_CONTENT, encoding="utf-8")
    return rules_dir


def create_rule(
    name: str,
    content: str,
    root: Path | None = None,
    trigger: str = "always_on",
) -> Path:
    """Create or seed a personal rule, guaranteeing valid trigger front matter."""
    rules_dir = ensure_personal_dir(root)
    file_name = name if name.endswith(".md") else f"{name}.md"
    path = rules_dir / file_name
    final_content = ensure_frontmatter(content, default_trigger=trigger)
    path.write_text(final_content, encoding="utf-8")
    return path


@dataclass(frozen=True)
class PersonalRule:
    name: str
    content: str
    path: Path


def rules(root: Path | None = None) -> list[PersonalRule]:
    folder = (root or personal_root()) / "rules"
    if not folder.is_dir():
        return []
    result: list[PersonalRule] = []
    for path in sorted(folder.glob("*.md")):
        if not path.is_file() or path.name.lower() == "readme.md":
            continue
        content = path.read_text(encoding="utf-8")
        check = check_frontmatter(content)
        if not check.valid:
            warnings.warn(
                f"Personal rule '{path.name}' ({path}) is missing YAML front matter with 'trigger: always_on' or 'trigger: glob'",
                UserWarning,
                stacklevel=2,
            )
        result.append(PersonalRule(path.stem, content, path.resolve()))
    return result


def _sync(root: Path | None = None) -> None:
    from .install.installer import sync_personal_rules

    sync_personal_rules(root=root)


def extract_section(text: str, title: str) -> tuple[str, str]:
    """Extract a markdown section by heading title, returning (section_text, remaining_text).

    Matches '# ... Title' or '## Title' case-insensitively.
    """
    clean_title = title.strip("#").strip()
    pattern = re.compile(
        rf"^(?P<hashes>#+)\s+{re.escape(clean_title)}\s*$",
        re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Section '{clean_title}' not found")
    level = len(match.group("hashes"))
    start_pos = match.start()

    next_pattern = re.compile(rf"^#{{1,{level}}}\s+", re.MULTILINE)
    next_match = next_pattern.search(text, pos=match.end())
    end_pos = next_match.start() if next_match else len(text)

    section_text = text[start_pos:end_pos].strip()
    remaining = (text[:start_pos].rstrip() + "\n\n" + text[end_pos:].lstrip()).strip()
    if remaining:
        remaining += "\n"
    return section_text, remaining


def list_rules(root: Path | None = None) -> int:
    from .install.agents import AGENTS

    r_root = root or personal_root()
    all_rules = rules(r_root)
    if not all_rules:
        emit_status("info", f"No personal rules found in {r_root / 'rules'}")
        return 0
    rows = []
    for r in all_rules:
        linked = []
        for agent_id, spec in sorted(AGENTS.items()):
            artifacts = spec.personal_artifacts([r])
            if any(a.path.is_symlink() for a in artifacts):
                linked.append(agent_id)
        rows.append((r.name, ", ".join(linked) or "none"))
    emit_rows(rows, headers=("Rule", "Agents"), full=True)
    return 0


@dataclass(frozen=True)
class RuleTarget:
    """Where a personal rule is written, shared by ``add_rule`` and ``migrate_rule``."""

    name: str
    force: bool = False
    root: Path | None = None


def _resolve_target(target: RuleTarget) -> tuple[Path, Path] | None:
    """The personal root and the rule path, or None after reporting why it cannot be used."""
    root = target.root or personal_root()
    rules_dir = ensure_personal_dir(root)
    file_name = target.name if target.name.endswith(".md") else f"{target.name}.md"
    path = rules_dir / file_name
    if path.exists() and not target.force:
        emit_status(
            "error",
            f"Personal rule '{path.stem}' already exists at {path}. Use --force to overwrite.",
        )
        return None
    return root, path


def _body_from_file(from_file: Path, title: str | None) -> str | None:
    """The source text with a heading if it has none, or None after reporting the missing file."""
    if not from_file.is_file():
        emit_status("error", f"Source file does not exist: {from_file}")
        return None
    content = from_file.read_text(encoding="utf-8")
    if title and not content.lstrip().startswith("#"):
        content = f"# {title}\n\n{content}"
    return content


def _template_body(name: str, title: str | None) -> str:
    heading = title or name.removesuffix(".md").replace("-", " ").replace("_", " ").title()
    return f"# {heading}\n\nRule contents...\n"


def add_rule(target: RuleTarget, *, from_file: Path | None = None, title: str | None = None) -> int:
    resolved = _resolve_target(target)
    if resolved is None:
        return 1
    root, _ = resolved
    if from_file:
        content = _body_from_file(from_file, title)
        if content is None:
            return 1
    else:
        content = _template_body(target.name, title)
    created = create_rule(target.name, content, root=root, trigger="always_on")
    _sync(root)
    emit_status("ok", f"Created personal rule '{created.stem}' at {created}")
    return 0


def _body_from_migration(from_file: Path, section: str | None) -> str | None:
    """Takes the section (or the whole file) out of the source, or None after reporting why not."""
    source_text = from_file.read_text(encoding="utf-8")
    if section is None:
        from_file.unlink()
        return source_text
    try:
        content, remaining = extract_section(source_text, section)
    except ValueError as exc:
        emit_status("error", str(exc))
        return None
    from_file.write_text(remaining, encoding="utf-8")
    return content


def migrate_rule(target: RuleTarget, *, from_file: Path, section: str | None = None) -> int:
    if not from_file.is_file():
        emit_status("error", f"Source file does not exist: {from_file}")
        return 1
    resolved = _resolve_target(target)
    if resolved is None:
        return 1
    root, _ = resolved
    content = _body_from_migration(from_file, section)
    if content is None:
        return 1
    created = create_rule(target.name, content, root=root, trigger="always_on")
    _sync(root)
    emit_status("ok", f"Migrated to personal rule '{created.stem}' at {created}")
    return 0


def remove_rule(name: str, *, root: Path | None = None) -> int:
    from .install.agents import AGENTS

    r_root = root or personal_root()
    rules_dir = r_root / "rules"
    file_name = name if name.endswith(".md") else f"{name}.md"
    rule_path = rules_dir / file_name
    stem = rule_path.stem

    existed = rule_path.is_file()
    if existed:
        rule_path.unlink()

    _sync(r_root)

    removed_links = 0
    fake_rule = PersonalRule(stem, "", rule_path)
    for spec in AGENTS.values():
        for artifact in spec.personal_artifacts([fake_rule]):
            if artifact.path.is_symlink() or artifact.path.exists():
                artifact.path.unlink()
                removed_links += 1

    if not existed and removed_links == 0:
        emit_status("error", f"Personal rule '{stem}' not found: {rule_path}")
        return 1

    emit_status("ok", f"Removed personal rule '{stem}' and its links.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-governance personal",
        description="Manage personal preference rules across agents.",
    )
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("list", help="List personal rules and the agents they are linked into")

    add_p = sub.add_parser("add", help="Create and link a new personal rule")
    add_p.add_argument("name", help="Rule name")
    add_p.add_argument(
        "--from", dest="from_file", type=Path, help="File to seed the rule content from"
    )
    add_p.add_argument("--title", help="Rule title for the heading")
    add_p.add_argument("--force", action="store_true", help="Overwrite existing personal rule")

    mig_p = sub.add_parser(
        "migrate", help="Migrate a file or markdown section into a personal rule"
    )
    mig_p.add_argument(
        "--from",
        dest="from_file",
        required=True,
        type=Path,
        help="Source markdown file (e.g. AGENTS.md)",
    )
    mig_p.add_argument("--name", required=True, help="Name for the personal rule")
    mig_p.add_argument(
        "--section",
        help="Optional heading of the section to extract; if omitted, migrates the entire file and removes it",
    )
    mig_p.add_argument("--force", action="store_true", help="Overwrite existing personal rule")

    rm_p = sub.add_parser("rm", help="Remove a personal rule and unlink it from all agents")
    rm_p.add_argument("name", help="Rule name to remove")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.action:
        parser.print_help()
        return 0
    if args.action == "list":
        return list_rules()
    if args.action == "add":
        return add_rule(
            RuleTarget(args.name, force=args.force),
            from_file=args.from_file,
            title=args.title,
        )
    if args.action == "migrate":
        return migrate_rule(
            RuleTarget(args.name, force=args.force),
            from_file=args.from_file,
            section=args.section,
        )
    if args.action == "rm":
        return remove_rule(args.name)
    return 0
