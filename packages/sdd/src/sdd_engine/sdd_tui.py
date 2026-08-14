"""
devscripts.cli.sdd_tui — Interactive Terminal User Interface (TUI) for selecting SDD AI Coding Agents.
"""

import json
import os
import sys
import termios
import tty
import select
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple

AGENTS_CATALOG = [
    {
        "id": "agy",
        "flag": "--agy",
        "name": "Google Antigravity 2.0 (AGY)",
        "desc": "AGENTS.md & .agents/skills/",
        "default": True,
    },
    {
        "id": "gemini",
        "flag": "--gemini",
        "name": "Gemini CLI",
        "desc": ".gemini/GEMINI.md",
        "default": True,
    },
    {
        "id": "claude",
        "flag": "--claude",
        "name": "Claude Code",
        "desc": "CLAUDE.md",
        "default": False,
    },
    {
        "id": "copilot",
        "flag": "--copilot",
        "name": "GitHub Copilot",
        "desc": ".github/copilot-instructions.md & .github/prompts/",
        "default": False,
    },
    {
        "id": "cursor",
        "flag": "--cursor",
        "name": "Cursor",
        "desc": ".cursorrules & .cursor/rules/",
        "default": False,
    },
    {
        "id": "chatgpt",
        "flag": "--chatgpt",
        "name": "ChatGPT / OpenAI",
        "desc": "CHATGPT.md",
        "default": False,
    },
]

COMPONENTS_CATALOG = [
    {
        "id": "rules",
        "name": "Global Rules",
        "desc": "Git workflow, practices",
        "default": True,
    },
    {
        "id": "skills",
        "name": "AI Skills",
        "desc": "Agent context files",
        "default": True,
    },
    {
        "id": "docs",
        "name": "Documentation",
        "desc": "SDD & architecture docs",
        "default": True,
    }
]

# ANSI Style escape codes
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"
REVERSE = "\033[7m"

def _read_key(tty_fd):
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        r, _, _ = select.select([sys.stdin], [], [], 0.1)
        if r:
            ch += sys.stdin.read(2)
    return ch

def render_tui(catalog: List[Dict[str, Any]], selected: List[bool], current_idx: int, title: str) -> str:
    lines = [
        "\033[H\033[J",
        f"====================================================================",
        f" 💫 {BOLD}SDD Toolkit — {title}{RESET} (GitHub Spec-Kit Aligned)",
        f"====================================================================",
        f" Select the items you want to configure for this workspace:",
        f" (Use {BOLD}↑/↓{RESET} arrows to navigate, {BOLD}[Space]{RESET} to toggle, {BOLD}[Enter]{RESET} to confirm)\n",
    ]

    for i, item in enumerate(catalog):
        check = f"{GREEN}[x]{RESET}" if selected[i] else f"[ ]"
        cursor = f"{CYAN}❯{RESET}" if i == current_idx else " "
        line_str = f"  {cursor} {check} {BOLD}{item['name']:<30}{RESET} {DIM}({item['desc']}){RESET}"
        
        if i == current_idx:
            lines.append(f"{REVERSE}{line_str}{RESET}\r\n")
        else:
            lines.append(f"{line_str}\r\n")

    lines.append(f"\n====================================================================")
    lines.append(f" Commands: {BOLD}[Space]{RESET} Toggle | {BOLD}[a]{RESET} Select All | {BOLD}[n]{RESET} Select None | {BOLD}[Enter]{RESET} Confirm\r\n")
    return "".join(lines)

def run_selector(catalog: List[Dict[str, Any]], title: str) -> List[str]:
    selected = [item["default"] for item in catalog]
    current_idx = 0

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?25l") # Hide cursor

        while True:
            sys.stdout.write(render_tui(catalog, selected, current_idx, title))
            sys.stdout.flush()

            key = _read_key(sys.stdin)

            if key in ("\x1b[A", "k"): # Up arrow
                current_idx = (current_idx - 1) % len(catalog)
            elif key in ("\x1b[B", "j"): # Down arrow
                current_idx = (current_idx + 1) % len(catalog)
            elif key == " ": # Space toggle
                selected[current_idx] = not selected[current_idx]
            elif key in ("a", "A"): # Select all
                selected = [True] * len(catalog)
            elif key in ("n", "N"): # Select none
                selected = [False] * len(catalog)
            elif key in ("\r", "\n"): # Enter confirm
                break
            elif key in ("\x03", "\x04"): # Ctrl+C / Ctrl+D
                sys.stdout.write("\033[?25h\n")
                sys.stdout.flush()
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                sys.exit(0)

    finally:
        sys.stdout.write("\033[?25h\n") # Show cursor
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return [catalog[i]["id"] for i, is_sel in enumerate(selected) if is_sel]

def run_agent_selector_tui() -> Tuple[List[str], List[str]]:
    if not sys.stdin.isatty():
        # Fallback to defaults when not in interactive TTY
        default_agents = [a["id"] for a in AGENTS_CATALOG if a["default"]]
        default_components = [c["id"] for c in COMPONENTS_CATALOG if c["default"]]
        return default_agents, default_components

    chosen_agents = run_selector(AGENTS_CATALOG, "AI Agent Selection")
    chosen_components = run_selector(COMPONENTS_CATALOG, "Components Selection")
    return chosen_agents, chosen_components

def save_agent_preferences(target_dir: Path, chosen_agents: List[str], chosen_components: List[str]):
    specify_dir = target_dir / ".specify"
    specify_dir.mkdir(parents=True, exist_ok=True)

    config_file = specify_dir / "agents.json"
    with open(config_file, "w") as f:
        json.dump({"selected_agents": chosen_agents, "selected_components": chosen_components}, f, indent=2)

    print(f"✅ Saved AI agent & component selection to: {config_file}")

def get_bridge_flags_for_agents(chosen_ids: List[str]) -> List[str]:
    flags = []
    for agent in AGENTS_CATALOG:
        if agent["id"] in chosen_ids:
            flags.append(agent["flag"])
    return flags

def main():
    chosen_agents, chosen_components = run_agent_selector_tui()
    save_agent_preferences(Path.cwd(), chosen_agents, chosen_components)
    flags = get_bridge_flags_for_agents(chosen_agents)
    print(f"Bridge flags: {' '.join(flags)}")

if __name__ == "__main__":
    main()
