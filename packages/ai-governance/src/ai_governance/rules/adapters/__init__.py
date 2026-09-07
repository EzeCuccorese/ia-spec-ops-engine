from .base import BaseAgentAdapter
from .codex import AgentsAdapter, CodexAdapter

ALL_ADAPTERS = {
    "agents": AgentsAdapter(),
}

__all__ = [
    "ALL_ADAPTERS",
    "AgentsAdapter",
    "BaseAgentAdapter",
    "CodexAdapter",
]
