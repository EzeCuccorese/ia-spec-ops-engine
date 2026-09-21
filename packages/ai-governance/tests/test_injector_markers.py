"""Tests for harness and rules block marker behavior in BlockInjector."""

from __future__ import annotations

from ai_governance.rules.core.injector import (
    END_MARKER,
    HARNESS_END_MARKER,
    HARNESS_START_MARKER,
    START_MARKER,
    BlockInjector,
)


def test_default_markers_inject_remove_roundtrip() -> None:
    """Default markers: inject and remove should roundtrip without data loss."""
    initial = "# User Notes\nCustom content here."
    body = "@~/.specops/rules/core/clean-code.md"

    injected = BlockInjector.inject(initial, body)
    assert START_MARKER in injected
    assert END_MARKER in injected
    assert body in injected

    removed = BlockInjector.remove(injected)
    assert removed.strip() == initial.strip()
    assert START_MARKER not in removed
    assert END_MARKER not in removed


def test_inject_harness_markers_with_existing_rules_block() -> None:
    """Injecting harness block when rules block exists → both present, each once."""
    rules_block = f"{START_MARKER}\n@rule1\n{END_MARKER}\n"
    content = f"# Header\n\n{rules_block}"
    harness_body = "## Harness Table\n| Trigger | Command |"

    result = BlockInjector.inject(
        content, harness_body, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER
    )

    assert result.count(START_MARKER) == 1
    assert result.count(END_MARKER) == 1
    assert result.count(HARNESS_START_MARKER) == 1
    assert result.count(HARNESS_END_MARKER) == 1
    assert "@rule1" in result


def test_inject_harness_twice_idempotent() -> None:
    """Injecting harness block twice → marker appears exactly once."""
    content = "# Header\n\nInitial content."
    harness_body = "## Harness Table\n| Trigger | Command |"

    injected_once = BlockInjector.inject(
        content, harness_body, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER
    )

    injected_twice = BlockInjector.inject(
        injected_once, harness_body, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER
    )

    assert injected_twice.count(HARNESS_START_MARKER) == 1
    assert injected_twice.count(HARNESS_END_MARKER) == 1
    assert injected_twice == injected_once


def test_remove_harness_block_preserves_rules_block() -> None:
    """Removing harness block when rules block exists → harness gone, rules intact."""
    rules_body = "@rule1"
    harness_body = "## Harness Table"

    content = "# Header\n\n"
    content = BlockInjector.inject(content, rules_body)
    content = BlockInjector.inject(
        content, harness_body, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER
    )

    cleaned = BlockInjector.remove(content, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER)

    assert HARNESS_START_MARKER not in cleaned
    assert HARNESS_END_MARKER not in cleaned
    assert START_MARKER in cleaned
    assert END_MARKER in cleaned
    assert "@rule1" in cleaned


def test_remove_rules_block_preserves_harness_block() -> None:
    """Removing rules block when harness block exists → rules gone, harness intact."""
    rules_body = "@rule1"
    harness_body = "## Harness Table"

    content = "# Header\n\n"
    content = BlockInjector.inject(content, rules_body)
    content = BlockInjector.inject(
        content, harness_body, start=HARNESS_START_MARKER, end=HARNESS_END_MARKER
    )

    cleaned = BlockInjector.remove(content)

    assert START_MARKER not in cleaned
    assert END_MARKER not in cleaned
    assert HARNESS_START_MARKER in cleaned
    assert HARNESS_END_MARKER in cleaned
    assert "## Harness Table" in cleaned


def test_remove_without_markers_returns_content_unchanged() -> None:
    """remove() is a no-op when the content has no start/end markers at all."""
    content = "# Plain file\nNo markers here."
    assert BlockInjector.remove(content) == content
