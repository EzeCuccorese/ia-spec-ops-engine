"""Splitting the big modules must not move their public import paths."""

from __future__ import annotations


def test_tui_names_still_importable_from_the_original_module() -> None:
    from workspace_engine.run_local import tui

    for name in (
        "_run_selection_tui",
        "_run_monitor_tui",
        "panel_run_config",
        "panel_monitor",
        "panel_confirm",
        "panel_profiles",
        "panel_source_picker",
    ):
        assert callable(getattr(tui, name))


def test_testquality_public_api_is_unchanged() -> None:
    from workspace_engine.design import testquality

    assert testquality.TEST_CHECKS and callable(testquality.junk_test_violations)
    assert callable(testquality.is_test_file) and testquality.Changed is not None
