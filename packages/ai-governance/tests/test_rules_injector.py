from ai_governance.rules.core.injector import END_MARKER, START_MARKER, BlockInjector


def test_inject_creates_new_block_on_empty_content() -> None:
    body = "@~/.specops/rules/core/clean-code.md"
    result = BlockInjector.inject("", body)
    assert START_MARKER in result
    assert END_MARKER in result
    assert body in result


def test_inject_preserves_user_content_intact() -> None:
    user_notes = "# My Project Notes\n\nCustom prompt instructions for the agent."
    body = "@~/.specops/rules/core/clean-code.md"
    result = BlockInjector.inject(user_notes, body)

    assert result.startswith(user_notes)
    assert START_MARKER in result
    assert body in result
    assert END_MARKER in result


def test_inject_updates_existing_block_without_duplicating() -> None:
    initial = f"# User Notes\n\n{START_MARKER}\n@old-rule\n{END_MARKER}\n"
    new_body = "@new-rule"
    result = BlockInjector.inject(initial, new_body)

    assert result.count(START_MARKER) == 1
    assert result.count(END_MARKER) == 1
    assert "@old-rule" not in result
    assert "@new-rule" in result
    assert "# User Notes" in result


def test_remove_cleans_only_block_preserving_user_notes() -> None:
    user_notes = "# User Notes\n\nPreserved prompt."
    content = f"{user_notes}\n\n{START_MARKER}\n@rule\n{END_MARKER}\n"
    cleaned = BlockInjector.remove(content)
    assert cleaned.strip() == user_notes.strip()


def test_remove_deletes_file_if_it_only_had_rules() -> None:
    content = f"{START_MARKER}\n@rule\n{END_MARKER}\n"
    cleaned = BlockInjector.remove(content)
    assert cleaned == ""
