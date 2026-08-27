from .base import BaseAgentAdapter
from .codex import CodexAdapter
from .claude import ClaudeAdapter
from .cursor import CursorAdapter
from .windsurf import WindsurfAdapter

ALL_ADAPTERS = {
    "codex": CodexAdapter(),
    "claude": ClaudeAdapter(),
    "cursor": CursorAdapter(),
    "windsurf": WindsurfAdapter(),
}
