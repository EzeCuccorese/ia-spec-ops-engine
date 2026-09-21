from pathlib import Path
from unittest.mock import patch

import pytest
from ai_governance.rules.core import hosts as hosts_module
from ai_governance.rules.core.catalog import TRIGGERS
from ai_governance.rules.core.hosts import (
    bindings_for,
    detect_host,
    known_hosts,
    validate_host_map,
)


def test_validate_host_map_passes() -> None:
    validate_host_map()


def test_bindings_for_claude_code_covers_all_automatic_triggers() -> None:
    bound = {binding.trigger for binding in bindings_for("claude-code")}
    automatic_triggers = TRIGGERS - {"on-demand"}
    assert automatic_triggers <= bound


def test_known_hosts_includes_claude_code() -> None:
    assert "claude-code" in known_hosts()


def test_bindings_for_unknown_host_is_empty() -> None:
    assert bindings_for("nonexistent-host") == ()


def test_detect_host_returns_none_without_claude_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert detect_host() is None


def test_detect_host_returns_claude_code_when_settings_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{}", encoding="utf-8")
    assert detect_host() == "claude-code"


def test_validate_host_map_raises_when_binding_missing() -> None:
    with (
        patch.object(hosts_module, "HOST_TRIGGER_MAP", {"claude-code": ()}),
        pytest.raises(ValueError, match="missing bindings"),
    ):
        validate_host_map()
