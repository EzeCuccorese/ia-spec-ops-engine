from .codex import AgentsAdapter, CodexAdapter

SPEC_ADAPTERS = {
    "agents": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "antigravity": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "codex": ("Universal AGENTS.md Standard (AGENTS.md)", CodexAdapter),
    "claude": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "cursor": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "windsurf": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "aider": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "copilot": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "gemini": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
    "custom": ("Universal AGENTS.md Standard (AGENTS.md)", AgentsAdapter),
}

__all__ = [
    "SPEC_ADAPTERS",
    "AgentsAdapter",
    "CodexAdapter",
]
