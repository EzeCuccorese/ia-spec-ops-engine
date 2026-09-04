from .base import BaseAgentAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .cursor import CursorAdapter
from .windsurf import WindsurfAdapter

ALL_ADAPTERS = {
    "codex": CodexAdapter(),
    "claude": ClaudeAdapter(),
    "cursor": CursorAdapter(),
    "windsurf": WindsurfAdapter(),
}

__all__ = [
    "ALL_ADAPTERS",
    "BaseAgentAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "CursorAdapter",
    "WindsurfAdapter",
]
