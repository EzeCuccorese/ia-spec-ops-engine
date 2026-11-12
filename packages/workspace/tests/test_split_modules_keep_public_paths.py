"""Splitting the big modules must not move their public import paths."""

from __future__ import annotations


def test_testquality_public_api_is_unchanged() -> None:
    from workspace_engine.design import testquality

    assert testquality.TEST_CHECKS and callable(testquality.junk_test_violations)
    assert callable(testquality.is_test_file) and testquality.Changed is not None
