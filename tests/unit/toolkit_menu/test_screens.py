"""Unit tests for toolkit-menu modal screens (FlagsScreen, ConfirmScreen).

Focuses on the on_key left/right handling: it must only steal the arrow keys
to move focus between action buttons when a Button is already focused —
otherwise it must let the key reach the focused widget untouched (e.g. cursor
movement inside an Input).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("textual")

_TOOLKIT_DIR = Path(__file__).resolve().parents[3]
_MENU_DIR = _TOOLKIT_DIR / "bin" / "toolkit-menu"
sys.path.insert(0, str(_MENU_DIR))


from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import Button, Input, Label, Switch  # noqa: E402

from catalog import Flag, Script  # noqa: E402
from screens import ConfirmScreen, FlagsScreen  # noqa: E402


def _script(**overrides) -> Script:
    defaults = dict(
        name="test-script",
        path="scripts/test.sh",
        summary="A test script.",
        danger="safe",
        interactive=False,
        contexts=("toolkit-root",),
        prereqs=(),
        flags=(Flag(flag="--name", type="value", help="a name"),),
    )
    defaults.update(overrides)
    return Script(**defaults)


class _FlagsHarness(App[None]):
    def __init__(self, script: Script) -> None:
        super().__init__()
        self.script = script

    def compose(self) -> ComposeResult:
        return []

    async def on_mount(self) -> None:
        await self.push_screen(FlagsScreen(self.script))


class _ConfirmHarness(App[None]):
    def __init__(self, script: Script, cmd: list[str]) -> None:
        super().__init__()
        self.script = script
        self.cmd = cmd

    def compose(self) -> ComposeResult:
        return []

    async def on_mount(self) -> None:
        await self.push_screen(ConfirmScreen(self.script, self.cmd))


@pytest.mark.asyncio
async def test_flags_screen_left_right_moves_cursor_inside_input() -> None:
    """Regression for F1: left/right inside a focused Input must move the
    text cursor, not jump focus to the action buttons."""
    app = _FlagsHarness(_script())
    async with app.run_test() as pilot:
        input_widget = app.screen.query_one("#f___name", Input)
        input_widget.focus()
        await pilot.pause()
        await pilot.press("a", "b", "c")
        await pilot.pause()
        start_cursor = input_widget.cursor_position

        await pilot.press("left")
        await pilot.pause()

        assert app.screen.focused is input_widget
        assert input_widget.cursor_position == start_cursor - 1


@pytest.mark.asyncio
async def test_flags_screen_left_right_still_moves_focus_between_buttons() -> None:
    """When a Button is focused, left/right should still cycle focus between
    the action buttons (the intended behavior)."""
    app = _FlagsHarness(_script())
    async with app.run_test() as pilot:
        run_button = app.screen.query_one("#run", Button)
        cancel_button = app.screen.query_one("#cancel", Button)
        run_button.focus()
        await pilot.pause()

        await pilot.press("right")
        await pilot.pause()

        assert app.screen.focused is cancel_button


def _two_switch_script(**overrides) -> Script:
    defaults = dict(
        flags=(
            Flag(flag="--no-host-deps", type="switch", help="no deps"),
            Flag(flag="--no-ai-statusline", type="switch", help="no statusline"),
        ),
    )
    defaults.update(overrides)
    return _script(**defaults)


def _mixed_script(**overrides) -> Script:
    defaults = dict(
        flags=(
            Flag(flag="--no-host-deps", type="switch", help="no deps"),
            Flag(flag="--no-ai-statusline", type="switch", help="no statusline"),
            Flag(flag="--name", type="value", help="a name"),
        ),
    )
    defaults.update(overrides)
    return _script(**defaults)


@pytest.mark.asyncio
async def test_flags_screen_digit_one_toggles_first_switch() -> None:
    app = _FlagsHarness(_two_switch_script())
    async with app.run_test() as pilot:
        first_switch = app.screen.query_one("#f___no_host_deps", Switch)
        assert first_switch.value is False

        await pilot.press("1")
        await pilot.pause()

        assert first_switch.value is True
        preview = app.screen.query_one("#cmd-preview")
        assert "--no-host-deps" in str(preview.render())


@pytest.mark.asyncio
async def test_flags_screen_digit_two_toggles_second_switch() -> None:
    app = _FlagsHarness(_two_switch_script())
    async with app.run_test() as pilot:
        first_switch = app.screen.query_one("#f___no_host_deps", Switch)
        second_switch = app.screen.query_one("#f___no_ai_statusline", Switch)

        await pilot.press("2")
        await pilot.pause()

        assert second_switch.value is True
        assert first_switch.value is False
        preview = app.screen.query_one("#cmd-preview")
        assert "--no-ai-statusline" in str(preview.render())


@pytest.mark.asyncio
async def test_flags_screen_digit_ignored_when_input_focused() -> None:
    app = _FlagsHarness(_mixed_script())
    async with app.run_test() as pilot:
        first_switch = app.screen.query_one("#f___no_host_deps", Switch)
        second_switch = app.screen.query_one("#f___no_ai_statusline", Switch)
        input_widget = app.screen.query_one("#f___name", Input)
        input_widget.focus()
        await pilot.pause()

        await pilot.press("1")
        await pilot.pause()

        assert first_switch.value is False
        assert second_switch.value is False
        assert "1" in input_widget.value


@pytest.mark.asyncio
async def test_flags_screen_up_down_navigates_all_focusable_widgets() -> None:
    app = _FlagsHarness(_two_switch_script())
    async with app.run_test() as pilot:
        run_button = app.screen.query_one("#run", Button)
        run_button.focus()
        await pilot.pause()

        await pilot.press("up")
        await pilot.pause()

        assert isinstance(app.screen.focused, Switch)


@pytest.mark.asyncio
async def test_flags_screen_switch_label_shows_shortcut_prefix() -> None:
    app = _FlagsHarness(_two_switch_script())
    async with app.run_test() as pilot:
        labels = list(app.screen.query(".flag-label").results(Label))
        texts = [str(label.render()) for label in labels]

        assert any("[1]" in t and "--no-host-deps" in t for t in texts)
        assert any("[2]" in t and "--no-ai-statusline" in t for t in texts)


@pytest.mark.asyncio
async def test_confirm_screen_left_right_still_moves_focus_between_buttons() -> None:
    app = _ConfirmHarness(_script(danger="destructive"), ["bash", "scripts/test.sh"])
    async with app.run_test() as pilot:
        no_button = app.screen.query_one("#no", Button)
        yes_button = app.screen.query_one("#yes", Button)
        no_button.focus()
        await pilot.pause()

        await pilot.press("left")
        await pilot.pause()

        assert app.screen.focused is yes_button
