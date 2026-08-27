from .codex import CodexAdapter
from .claude import ClaudeAdapter
from .cursor import CursorAdapter
from .windsurf import WindsurfAdapter

SPEC_ADAPTERS = {
    "antigravity": ("Google Antigravity & Universal Codex (AGENTS.md)", CodexAdapter),
    "claude": ("Anthropic Claude Code (CLAUDE.md)", ClaudeAdapter),
    "cursor": ("Cursor IDE (.cursorrules)", CursorAdapter),
    "windsurf": ("Codeium Windsurf (.windsurfrules)", WindsurfAdapter),
}
