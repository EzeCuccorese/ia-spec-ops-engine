from .aider import AiderAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .copilot import CopilotAdapter
from .cursor import CursorAdapter
from .custom import CustomAdapter
from .gemini import GeminiAdapter
from .windsurf import WindsurfAdapter

SPEC_ADAPTERS = {
    "antigravity": ("Google Antigravity & Universal Codex (AGENTS.md)", CodexAdapter),
    "codex": ("Universal Codex / AGENTS.md (AGENTS.md)", CodexAdapter),
    "claude": ("Anthropic Claude Code (CLAUDE.md)", ClaudeAdapter),
    "cursor": ("Cursor IDE (.cursorrules)", CursorAdapter),
    "windsurf": ("Codeium Windsurf (.windsurfrules)", WindsurfAdapter),
    "aider": ("Aider AI (.aider.conf.yml)", AiderAdapter),
    "copilot": ("GitHub Copilot (.github/copilot-instructions.md)", CopilotAdapter),
    "gemini": ("Google Gemini CLI (GEMINI.md)", GeminiAdapter),
    "custom": ("Custom Agent Target File", CustomAdapter),
}

__all__ = [
    "SPEC_ADAPTERS",
    "AiderAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "CopilotAdapter",
    "CursorAdapter",
    "CustomAdapter",
    "GeminiAdapter",
    "WindsurfAdapter",
]

