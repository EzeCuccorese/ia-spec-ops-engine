"""
Integration tests for terminal formatting, ANSI stripping, and TTY primitives.
"""

from devscripts.core.terminal import strip_ansi, pad_colored, draw_separator

def test_strip_ansi_codes():
    colored_str = "\033[1m\033[32mHello World\033[0m"
    assert strip_ansi(colored_str) == "Hello World"

def test_pad_colored_length():
    plain = "Status OK"
    colored = "\033[32mStatus OK\033[0m"
    padded = pad_colored(plain, 15, colored)
    assert len(strip_ansi(padded)) == 15

def test_draw_separator():
    sep = draw_separator(20, char="─", bold=False)
    assert sep == "────────────────────"
