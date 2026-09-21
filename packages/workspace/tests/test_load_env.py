"""
Unit tests for workspace_engine.cli.load_env.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from workspace_engine.cli.load_env import main, update_env_in_yaml

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


def test_update_env_in_yaml_handles_none_config_map_properties(tmp_path: Path) -> None:
    yaml_path = tmp_path / "values.dev.yaml"
    yaml_path.write_text(
        "apps:\n  - name: service-a\n    configMapProperties: null\n", encoding="utf-8"
    )
    result = update_env_in_yaml(yaml_path, ["service-a"], "FEATURE_FLAG", "on")
    assert result is True
    assert "FEATURE_FLAG: on" in yaml_path.read_text(encoding="utf-8")


def test_update_env_in_yaml_write_failure_returns_false(tmp_path: Path) -> None:
    yaml_path = tmp_path / "values.dev.yaml"
    yaml_path.write_text(SAMPLE_YAML, encoding="utf-8")

    try:
        yaml_path.chmod(stat.S_IREAD)
        result = update_env_in_yaml(yaml_path, ["service-a"], "FEATURE_FLAG", "on")
        assert result is False
    finally:
        yaml_path.chmod(stat.S_IREAD | stat.S_IWRITE)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_updates_matching_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = tmp_path / "gitops"
    root_dir.mkdir()
    (root_dir / "values.dev.yaml").write_text(SAMPLE_YAML, encoding="utf-8")
    (root_dir / "values.staging.yaml").write_text(SAMPLE_YAML, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "load-env",
            "--envs",
            "dev,staging,prod",
            "--services",
            "service-a",
            "--var",
            "FEATURE_FLAG",
            "--values",
            "on,off",
            "--root",
            str(root_dir),
        ],
    )
    main()

    dev_content = (root_dir / "values.dev.yaml").read_text(encoding="utf-8")
    assert 'FEATURE_FLAG: "on"' in dev_content
    staging_content = (root_dir / "values.staging.yaml").read_text(encoding="utf-8")
    assert 'FEATURE_FLAG: "off"' in staging_content
    # "prod" has no matching value and no file was created for it.
    assert not (root_dir / "values.prod.yaml").exists()


def test_main_applies_suffix_to_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = tmp_path / "gitops"
    root_dir.mkdir()
    (root_dir / "values.dev.yaml").write_text(SAMPLE_YAML, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "load-env",
            "--envs",
            "dev",
            "--services",
            "service-a",
            "--var",
            "FEATURE_FLAG",
            "--values",
            "on",
            "--suffix",
            "_suffix",
            "--root",
            str(root_dir),
        ],
    )
    with patch("workspace_engine.cli.load_env.update_env_in_yaml") as mock_update:
        main()
    mock_update.assert_called_once_with(
        root_dir / "values.dev.yaml", ["service-a"], "FEATURE_FLAG", "on_suffix"
    )


def test_main_default_root_uses_home_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "load-env",
            "--envs",
            "dev",
            "--services",
            "service-a",
            "--var",
            "FEATURE_FLAG",
            "--values",
            "on",
        ],
    )
    with patch("workspace_engine.cli.load_env.update_env_in_yaml") as mock_update:
        main()
    called_path = mock_update.call_args.args[0]
    assert str(called_path).endswith("values.dev.yaml")
    assert os.path.expanduser("~") in str(called_path)
