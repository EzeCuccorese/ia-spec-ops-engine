from .aider import AiderAdapter
from .base import BaseAgentAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .copilot import CopilotAdapter
from .cursor import CursorAdapter
from .gemini import GeminiAdapter
from .windsurf import WindsurfAdapter

ALL_ADAPTERS = {
    "codex": CodexAdapter(),
    "claude": ClaudeAdapter(),
    "cursor": CursorAdapter(),
    "windsurf": WindsurfAdapter(),
    "aider": AiderAdapter(),
    "copilot": CopilotAdapter(),
    "gemini": GeminiAdapter(),
}

__all__ = [
    "ALL_ADAPTERS",
    "AiderAdapter",
    "BaseAgentAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "CopilotAdapter",
    "CursorAdapter",
    "GeminiAdapter",
    "WindsurfAdapter",
]

