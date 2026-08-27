from __future__ import annotations

import os
import sys
from typing import Sequence

# ANSI Colors and Controls
CLEAR_LINE = "\033[2K"
CURSOR_UP = "\033[1A"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def get_key() -> str:
    """Reads a single key or escape sequence from stdin."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch1 = sys.stdin.read(1)
        if ch1 == "\x1b":  # ESC sequence
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "UP"
                elif ch3 == "B":
                    return "DOWN"
                elif ch3 == "C":
                    return "RIGHT"
                elif ch3 == "D":
                    return "LEFT"
            return "ESC"
        elif ch1 == "\r" or ch1 == "\n":
            return "ENTER"
        elif ch1 == " ":
            return "SPACE"
        elif ch1 == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        return ch1
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def select_one(
    title: str,
    options: Sequence[str],
    default_index: int = 0,
) -> int:
    """Arrow-key single selection menu (↑/↓ to navigate, Enter to select)."""
    if not sys.stdin.isatty():
        return default_index

    current = default_index
    num_options = len(options)

    print(f"\n{BOLD}{YELLOW}? {title}{RESET} {DIM}(Use ↑/↓ arrows, Enter to select){RESET}")
    print(HIDE_CURSOR, end="", flush=True)

    try:
        # Initial render
        for i, opt in enumerate(options):
            prefix = f"{CYAN}❯{RESET} {BOLD}{opt}{RESET}" if i == current else f"  {DIM}{opt}{RESET}"
            print(f"  {prefix}")

        while True:
            key = get_key()
            if key == "UP":
                current = (current - 1) % num_options
            elif key == "DOWN":
                current = (current + 1) % num_options
            elif key == "ENTER":
                break

            # Move cursor up and redraw
            print(f"\033[{num_options}A", end="")
            for i, opt in enumerate(options):
                prefix = f"{CYAN}❯{RESET} {BOLD}{opt}{RESET}" if i == current else f"  {DIM}{opt}{RESET}"
                print(f"{CLEAR_LINE}  {prefix}")
            sys.stdout.flush()

    finally:
        print(SHOW_CURSOR, end="", flush=True)

    print(f"{CLEAR_LINE}{GREEN}✔{RESET} Selected: {BOLD}{options[current]}{RESET}\n")
    return current


def select_multiple(
    title: str,
    options: Sequence[tuple[str, str]],  # (id, label)
    default_checked: Sequence[str] | None = None,
) -> list[str]:
    """Arrow-key multi-selection menu (↑/↓ to navigate, Space to toggle, 'a' for all, Enter to submit)."""
    if not sys.stdin.isatty():
        return [opt[0] for opt in options] if default_checked is None else list(default_checked)

    checked = set(default_checked or [opt[0] for opt in options])
    current = 0
    num_options = len(options)

    print(f"\n{BOLD}{YELLOW}? {title}{RESET} {DIM}(↑/↓ navigate, Space toggle, 'a' toggle all, Enter confirm){RESET}")
    print(HIDE_CURSOR, end="", flush=True)

    try:
        # Initial render
        for i, (opt_id, opt_label) in enumerate(options):
            is_chk = opt_id in checked
            chk_mark = f"{GREEN}[X]{RESET}" if is_chk else f"{DIM}[ ]{RESET}"
            cursor = f"{CYAN}❯{RESET}" if i == current else " "
            label = f"{BOLD}{opt_label}{RESET}" if i == current else f"{opt_label}"
            print(f"  {cursor} {chk_mark} {label}")

        while True:
            key = get_key()
            if key == "UP":
                current = (current - 1) % num_options
            elif key == "DOWN":
                current = (current + 1) % num_options
            elif key == "SPACE":
                opt_id = options[current][0]
                if opt_id in checked:
                    checked.remove(opt_id)
                else:
                    checked.add(opt_id)
            elif key in ("a", "A"):
                if len(checked) == num_options:
                    checked.clear()
                else:
                    checked = {opt[0] for opt in options}
            elif key == "ENTER":
                break

            # Redraw
            print(f"\033[{num_options}A", end="")
            for i, (opt_id, opt_label) in enumerate(options):
                is_chk = opt_id in checked
                chk_mark = f"{GREEN}[X]{RESET}" if is_chk else f"{DIM}[ ]{RESET}"
                cursor = f"{CYAN}❯{RESET}" if i == current else " "
                label = f"{BOLD}{opt_label}{RESET}" if i == current else f"{opt_label}"
                print(f"{CLEAR_LINE}  {cursor} {chk_mark} {label}")
            sys.stdout.flush()

    finally:
        print(SHOW_CURSOR, end="", flush=True)

    print(f"{CLEAR_LINE}{GREEN}✔{RESET} Selected {BOLD}{len(checked)}{RESET} items.\n")
    return [opt[0] for opt in options if opt[0] in checked]
