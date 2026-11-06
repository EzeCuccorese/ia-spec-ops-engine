"""Personal preference packs (``~/.config/ai-governance/personal/``): always-on rules.

Personal rules live outside the repository in ``$AI_GOVERNANCE_PERSONAL_DIR`` or
``$AI_GOVERNANCE_CONFIG_DIR/personal`` (default ``~/.config/ai-governance/personal``).
Every rule present in ``<root>/rules/*.md`` is installed as a symlink for each selected agent.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import check_frontmatter, ensure_frontmatter
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
