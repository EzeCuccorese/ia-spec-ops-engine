"""Keyboard-driven service configuration preserves the choices sent to the launcher."""

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from workspace_engine.run_local import constants, tui_config, tui_panels

ScreenResult = tuple[list | None, str]


@pytest.fixture
def config_ui(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., ScreenResult]:
    repos = [
        {"name": name, "path": tmp_path / name, "port": 8000 + i, "type": "node"}
        for i, name in enumerate(("alpha", "beta"))
    ]
    environments = [{"id": "local", "cluster": None}, {"id": "dev", "cluster": "dev"}]
    monkeypatch.setattr(tui_config, "get_environments", lambda: environments)
    monkeypatch.setattr(tui_config, "load_state", lambda: ([], []))
    monkeypatch.setattr(tui_config, "_get_kubectl_contexts", lambda: ["dev"])
    monkeypatch.setattr(constants, "PROFILES_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr(constants, "CONFIG_DIR", tmp_path)

    def play(keys: list[bytes], *, local_config: bool = True) -> ScreenResult:
        keyboard = iter(keys)
        output: list[str] = []
        for module in (tui_config, tui_panels):
            monkeypatch.setattr(module, "_read_key", lambda *args: next(keyboard))
            monkeypatch.setattr(module, "_w", lambda fd, text: output.append(text))
        monkeypatch.setattr(tui_config, "_kubectl_available", lambda: True)
        monkeypatch.setattr(
            tui_config, "resolve_local_env", lambda *args: tmp_path if local_config else None
        )
        result = tui_config.panel_run_config(BytesIO(), repos, {})
        return result, "".join(output)

    return play


def test_filtered_selection_keeps_other_services_and_their_launch_settings(config_ui) -> None:
    result, _ = config_ui([b"\x1b[B", b" ", b"b", b"\x1b[B", b" ", b"\x1b[C", b"d", b"m", b"\r"])
    assert result is not None
    settings = {
        service["name"]: (service["base_env"], service["db_env"], service["up_mode"])
        for service in result
    }
    assert settings == {"alpha": ("local", "local", "auto"), "beta": ("dev", "dev", "dev")}


def test_missing_local_config_blocks_launch_until_a_remote_environment_is_selected(
    config_ui,
) -> None:
    result, output = config_ui(
        [b"\r", b"\x1b[B", b" ", b"\r", b"\x1b[C", b"\r"], local_config=False
    )
    assert "Select at least one service" in output
    assert "alpha: no set-env (local environment)" in output
    assert result is not None and len(result) == 1
    assert result[0]["name"] == "alpha" and result[0]["base_env"] == "dev"


def test_saved_profile_restores_a_selection_after_it_is_cleared(config_ui, tmp_path: Path) -> None:
    result, output = config_ui(
        [b"\x1b[B", b" ", b"g", b"d", b"e", b"m", b"o", b"\r", b" ", b"p", b"\r", b"\r"]
    )
    assert (tmp_path / "profiles.json").is_file()
    assert 'Profile "demo" saved (1 services)' in output
    assert "Profile loaded" in output
    assert result is not None
    assert [(service["name"], service["base_env"]) for service in result] == [("alpha", "local")]
