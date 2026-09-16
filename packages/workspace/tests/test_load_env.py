"""
Unit tests for workspace_engine.cli.load_env.update_env_in_yaml.
"""

from __future__ import annotations

from pathlib import Path

from workspace_engine.cli.load_env import update_env_in_yaml

SAMPLE_YAML = """\
apps:
  - name: service-a
    configMapProperties:
      FEATURE_FLAG: "off"
  - name: service-b
"""


def test_update_env_in_yaml_updates_matching_service(tmp_path: Path) -> None:
    yaml_path = tmp_path / "values.dev.yaml"
    yaml_path.write_text(SAMPLE_YAML, encoding="utf-8")

    result = update_env_in_yaml(yaml_path, ["service-a"], "FEATURE_FLAG", "on")

    assert result is True
    updated = yaml_path.read_text(encoding="utf-8")
    assert 'FEATURE_FLAG: "on"' in updated
    # Untouched service is left as-is.
    assert "service-b" in updated


def test_update_env_in_yaml_creates_config_map_when_missing(tmp_path: Path) -> None:
    yaml_path = tmp_path / "values.dev.yaml"
    yaml_path.write_text(SAMPLE_YAML, encoding="utf-8")

    result = update_env_in_yaml(yaml_path, ["service-b"], "NEW_VAR", "value")

    assert result is True
    updated = yaml_path.read_text(encoding="utf-8")
    assert "NEW_VAR: value" in updated


def test_update_env_in_yaml_no_changes_when_value_already_set(tmp_path: Path) -> None:
    yaml_path = tmp_path / "values.dev.yaml"
    yaml_path.write_text(SAMPLE_YAML, encoding="utf-8")

    result = update_env_in_yaml(yaml_path, ["service-a"], "FEATURE_FLAG", "off")

    assert result is True


def test_update_env_in_yaml_missing_file_returns_false(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yaml"
    assert update_env_in_yaml(missing, ["service-a"], "FEATURE_FLAG", "on") is False
