"""Phase 0: one default domain/url_pattern, and no config read at import time."""

from __future__ import annotations

import json
import re
from pathlib import Path

from workspace_engine.config.init_config import generate_default_config
from workspace_engine.run_local import constants


def test_default_config_matches_what_config_init_writes(tmp_path: Path) -> None:
    cfg = constants.load_project_config(start_dir=tmp_path)
    generated = generate_default_config("generic", constants.DEFAULT_DOMAIN)
    assert cfg["domain"] == generated["domain"] == "local.dev"
    assert cfg["url_pattern"] == generated["url_pattern"]
    match = re.search(cfg["url_pattern"], "http://orders.dev.local.dev/api")
    assert match is not None and match.group(1) == "orders"


def test_domain_in_user_config_derives_the_url_pattern(tmp_path: Path) -> None:
    (tmp_path / ".workspace").mkdir()
    (tmp_path / ".workspace" / "config.json").write_text(json.dumps({"domain": "acme.io"}))
    (tmp_path / ".git").mkdir()
    cfg = constants.load_project_config(start_dir=tmp_path)
    assert re.search(cfg["url_pattern"], "https://orders.prod.acme.io/x")


def test_import_does_not_load_config(monkeypatch) -> None:
    calls: list[object] = []
    real = constants.load_project_config
    monkeypatch.setattr(constants, "load_project_config", lambda *a, **k: calls.append(1) or real())
    constants._LAZY_CACHE.clear()
    assert calls == []
    constants.get_project_config()
    constants.get_project_config()
    assert calls == [1]
    constants._LAZY_CACHE.clear()
