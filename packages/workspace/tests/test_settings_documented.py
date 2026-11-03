"""Every setting has a row (key and env var) in the package README."""

from pathlib import Path

from workspace_engine.settings import SETTINGS


def test_every_setting_is_documented() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    missing = [s.key for s in SETTINGS if f"| `{s.key}` | `{s.env}` |" not in readme]
    assert not missing, missing
