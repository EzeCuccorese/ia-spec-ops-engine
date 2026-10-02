"""Tests for workspace_engine.run_local.main: source resolution, headless start and the
monitor loop that adds or reconfigures services."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

MAIN = "workspace_engine.run_local.main"
# The package re-exports `main` the function, which shadows the submodule attribute.
rl = importlib.import_module(MAIN)


def _result(name: str, pid: int | None = 100, ok: bool = True) -> dict:
    return {"name": name, "pid": pid, "ok": ok}


def _config(name: str, base_env: str = "local") -> dict:
    return {"name": name, "base_env": base_env, "db_env": "local", "up_mode": "auto"}


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def test_forced_repos_dir_requires_a_git_repository(tmp_path: Path):
    assert rl._forced_repos_dir(None) is None
    assert rl._forced_repos_dir(str(tmp_path)) is None
    (tmp_path / "api" / ".git").mkdir(parents=True)
    assert rl._forced_repos_dir(str(tmp_path)) == tmp_path.resolve()


def test_resolve_sources_uses_the_forced_directory(tmp_path: Path):
    (tmp_path / "api" / ".git").mkdir(parents=True)
    sources, forced = rl._resolve_sources(str(tmp_path))
    assert forced == tmp_path.resolve()
    assert sources == [{"label": tmp_path.name, "path": forced, "kind": "repos"}]


def test_resolve_sources_lists_the_project_sources(tmp_path: Path):
    (tmp_path / "repositories").mkdir()
    sources, forced = rl._resolve_sources(str(tmp_path))
    assert forced is None
    assert sources[0]["path"] == tmp_path.resolve() / "repositories"


def test_resolve_sources_exits_without_a_project(tmp_path: Path, capsys):
    with patch(f"{MAIN}.find_project_root", return_value=None), pytest.raises(SystemExit):
        rl._resolve_sources(str(tmp_path))
    assert "no project found" in capsys.readouterr().out


def test_resolve_sources_exits_without_sources(tmp_path: Path, capsys):
    with (
        patch(f"{MAIN}.find_project_root", return_value=tmp_path),
        pytest.raises(SystemExit),
    ):
        rl._resolve_sources(str(tmp_path))
    assert "no sources found" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --start
# ---------------------------------------------------------------------------


def test_last_configs_to_start_filters_by_name():
    with patch(f"{MAIN}.load_last_configs", return_value=[_config("api"), _config("web")]):
        assert [c["name"] for c in rl._last_configs_to_start("web, ")] == ["web"]
        assert len(rl._last_configs_to_start("")) == 2


@pytest.mark.parametrize(
    ("saved", "spec", "message"),
    [
        ([], "", "No saved config. Run `ws run-local` without --start first."),
        ([_config("api")], "web", "No repo found"),
    ],
)
def test_last_configs_to_start_exits_when_nothing_matches(saved, spec, message, capsys):
    with patch(f"{MAIN}.load_last_configs", return_value=saved), pytest.raises(SystemExit):
        rl._last_configs_to_start(spec)
    assert message in capsys.readouterr().out


def test_start_headless_skips_running_services(capsys):
    with (
        patch(f"{MAIN}.load_last_configs", return_value=[_config("api")]),
        patch(f"{MAIN}._pid_alive", return_value=True),
        patch(f"{MAIN}._launch_and_report") as launch,
    ):
        rl._start_headless("", [_result("api")], [_config("api")], {})
    launch.assert_not_called()
    assert "already running" in capsys.readouterr().out


def test_start_headless_launches_and_keeps_only_started(capsys):
    results: list = []
    launch_configs: list = []
    launched = ([_result("api"), _result("web", ok=False)], [_config("api"), _config("web")])
    with (
        patch(f"{MAIN}.load_last_configs", return_value=[_config("api"), _config("web")]),
        patch(f"{MAIN}._launch_and_report", return_value=launched),
        patch(f"{MAIN}.save_state") as save,
    ):
        rl._start_headless("", results, launch_configs, {})
    assert [r["name"] for r in results] == ["api"]
    assert [c["name"] for c in launch_configs] == ["api"]
    save.assert_called_once_with(results, launch_configs)
    assert "Stop: ws run-local --stop" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# First launch and monitor loop
# ---------------------------------------------------------------------------


def test_launch_selection_cancelled():
    with patch(f"{MAIN}._run_selection_tui", return_value=[]):
        assert rl._launch_selection([], None, {}) == ([], [])


def test_launch_selection_saves_started_services():
    launched = ([_result("api"), _result("web", ok=False)], [_config("api"), _config("web")])
    with (
        patch(f"{MAIN}._run_selection_tui", return_value=[_config("api"), _config("web")]),
        patch(f"{MAIN}._launch_and_report", return_value=launched),
        patch(f"{MAIN}.save_state"),
        patch(f"{MAIN}.save_last_configs") as save_last,
    ):
        results, launch_configs = rl._launch_selection([], None, {})
    assert [r["name"] for r in results] == ["api"]
    save_last.assert_called_once_with([_config("api")])


@pytest.mark.parametrize(
    ("current", "alive", "expected"),
    [
        (None, {"api"}, True),
        (_config("api"), set(), True),
        (_config("api"), {"api"}, False),
        (_config("api", base_env="staging"), {"api"}, True),
    ],
)
def test_needs_launch(current, alive, expected):
    assert rl._needs_launch(_config("api"), current, alive) is expected


def test_stop_running_terminates_the_process_group():
    with (
        patch(f"{MAIN}._pid_alive", return_value=True),
        patch(f"{MAIN}.os.kill", side_effect=[ProcessLookupError, None]) as kill,
    ):
        rl._stop_running([_config("api"), _config("web")], [_result("api", pid=42)])
    assert [c.args for c in kill.call_args_list] == [(-42, 15), (42, 15)]


@pytest.mark.parametrize(("answer", "restarts"), [("y", 1), ("", 0), (EOFError, 0)])
def test_offer_rewire(answer, restarts, capsys):
    with (
        patch(f"{MAIN}._dependents_to_rewire", return_value=["web"]),
        patch("builtins.input", side_effect=[answer]),
        patch(f"{MAIN}._restart_named") as restart,
        patch(f"{MAIN}.save_state"),
    ):
        rl._offer_rewire([], [], {"api"}, {})
    assert restart.call_count == restarts
    assert "web" in capsys.readouterr().out


def test_offer_rewire_without_dependents(capsys):
    with patch(f"{MAIN}._dependents_to_rewire", return_value=[]), patch("builtins.input") as ask:
        rl._offer_rewire([], [], {"api"}, {})
    ask.assert_not_called()
    assert capsys.readouterr().out == ""


def test_add_services_nothing_changed():
    results, launch_configs = [_result("api")], [_config("api")]
    with (
        patch(f"{MAIN}._pid_alive", return_value=True),
        patch(f"{MAIN}._launch_and_report") as launch,
    ):
        assert rl._add_services([_config("api")], results, launch_configs, {}) == (
            results,
            launch_configs,
        )
    launch.assert_not_called()


def test_add_services_replaces_the_relaunched_entries():
    results = [_result("api", pid=1), _result("web", pid=2)]
    launch_configs = [_config("api"), _config("web")]
    relaunched = _config("api", base_env="staging")
    with (
        patch(f"{MAIN}._pid_alive", return_value=True),
        patch(f"{MAIN}.os.kill"),
        patch(
            f"{MAIN}._launch_and_report",
            return_value=([_result("api", pid=3)], [relaunched]),
        ),
        patch(f"{MAIN}.save_state"),
        patch(f"{MAIN}.save_last_configs"),
        patch(f"{MAIN}._offer_rewire") as rewire,
    ):
        results, launch_configs = rl._add_services([relaunched], results, launch_configs, {})
    assert [(r["name"], r["pid"]) for r in results] == [("web", 2), ("api", 3)]
    assert launch_configs[-1] is relaunched
    rewire.assert_called_once()


def test_monitor_adds_until_the_user_quits(capsys):
    select_calls = iter([[], [_config("web")]])
    with (
        patch(f"{MAIN}._run_monitor_tui", side_effect=["add", "add", "quit"]),
        patch(f"{MAIN}.save_state"),
        patch(f"{MAIN}._add_services", return_value=([], [])) as add,
    ):
        rl._monitor([], [], lambda: next(select_calls), {})
    add.assert_called_once_with([_config("web")], [], [], {})
    assert capsys.readouterr().out.count("Stop: ws run-local --stop") == 3


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "repositories").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_main_start_reattaches_and_relaunches(project: Path, capsys):
    with (
        patch(f"{MAIN}._ensure_config", return_value={}),
        patch(f"{MAIN}.load_state", return_value=([_result("api")], [_config("api")])),
        patch(f"{MAIN}._start_headless") as start,
    ):
        rl.main(["--start", "api"])
    assert "Reattaching 1 running service(s)" in capsys.readouterr().out
    assert start.call_args.args[0] == "api"


def test_main_returns_when_nothing_was_launched(project: Path, capsys):
    with (
        patch(f"{MAIN}._ensure_config", return_value={}),
        patch(f"{MAIN}.load_state", return_value=([], [])),
        patch(f"{MAIN}._launch_selection", return_value=([], [])),
        patch(f"{MAIN}._monitor") as monitor,
    ):
        rl.main([])
    monitor.assert_not_called()
    assert "Services keep running" not in capsys.readouterr().out


def test_main_monitors_launched_services(project: Path, capsys):
    with (
        patch(f"{MAIN}._ensure_config", return_value={}),
        patch(f"{MAIN}.load_state", return_value=([], [])),
        patch(f"{MAIN}._launch_selection", return_value=([_result("api")], [_config("api")])),
        patch(f"{MAIN}._run_selection_tui", return_value=None) as select,
        patch(f"{MAIN}._monitor") as monitor,
    ):
        rl.main([])
        monitor.call_args.args[2]()
    select.assert_called_once()
    out = capsys.readouterr().out
    assert "Services keep running in the background. Use `ws run-local --stop`" in out


def test_missing_config_lists_the_real_search_order(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    with pytest.raises(SystemExit) as exc:
        rl._exit_without_config()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    expected = [
        tmp_path / ".workspace" / "config.json",
        tmp_path / "xdg" / "workspace" / "config.json",
        tmp_path / "home" / ".config" / "workspace" / "config.json",
        tmp_path / "config.json",
    ]
    positions = [out.index(str(path) + "\n") for path in expected]
    assert positions == sorted(positions)
    assert "ws config init" in out


def test_terminate_ignores_processes_it_cannot_signal():
    with patch(f"{MAIN}.os.kill", side_effect=PermissionError) as kill:
        rl._terminate(42)
    assert [c.args for c in kill.call_args_list] == [(-42, 15), (42, 15)]


def test_terminate_never_signals_its_own_process_group():
    with patch(f"{MAIN}.os.kill") as kill:
        rl._terminate(0)
    assert kill.call_args_list == []


def test_add_services_drops_a_stopped_service_that_failed_to_relaunch():
    results = [_result("api", pid=1), _result("web", pid=2)]
    launch_configs = [_config("api"), _config("web")]
    relaunched = _config("api", base_env="staging")
    with (
        patch(f"{MAIN}._pid_alive", return_value=True),
        patch(f"{MAIN}.os.kill"),
        patch(
            f"{MAIN}._launch_and_report",
            return_value=([_result("api", pid=None, ok=False)], [relaunched]),
        ),
        patch(f"{MAIN}.save_state"),
        patch(f"{MAIN}.save_last_configs"),
        patch(f"{MAIN}._offer_rewire"),
    ):
        results, launch_configs = rl._add_services([relaunched], results, launch_configs, {})
    assert [r["name"] for r in results] == ["web"]
    assert [c["name"] for c in launch_configs] == ["web"]


def test_stop_works_without_a_configuration(monkeypatch, capsys):
    import sys

    monkeypatch.setattr(rl, "_CONFIG_LOADED", False)
    monkeypatch.delitem(sys.modules, "pytest")
    with patch(f"{MAIN}.stop_all") as stop:
        rl.main(["--stop"])
    stop.assert_called_once_with()
    assert "no configuration found" not in capsys.readouterr().out


def test_needs_launch_tolerates_configs_without_mode_keys():
    assert rl._needs_launch({"name": "api"}, {"name": "api"}, {"api"}) is False


def test_stop_running_waits_for_the_port_before_relaunch():
    events: list[tuple] = []
    with (
        patch(f"{MAIN}._pid_alive", return_value=True),
        patch(f"{MAIN}.os.kill", side_effect=lambda pid, sig: events.append(("kill", pid))),
        patch(f"{MAIN}._wait_port_free", side_effect=lambda port: events.append(("wait", port))),
    ):
        rl._stop_running([{**_config("api"), "port": 8123}], [_result("api", pid=42)])
    assert events == [("kill", -42), ("kill", 42), ("wait", 8123)]


def test_restart_named_ignores_processes_it_cannot_signal():
    results = [_result("api", pid=42)]
    launch_configs = [{**_config("api"), "port": 8123}]
    with (
        patch(f"{MAIN}.os.kill", side_effect=PermissionError),
        patch(f"{MAIN}._wait_port_free"),
        patch(f"{MAIN}._launch_one", return_value=(43, None, 1.0, {})),
    ):
        rl._restart_named(["api"], results, launch_configs, {})
    assert results[0]["pid"] == 43


@pytest.mark.parametrize("own", ["getpid", "getpgrp"])
def test_terminate_never_signals_ws_itself(own):
    import os

    pid = getattr(os, own)()
    with patch(f"{MAIN}.os.kill") as kill:
        rl._terminate(pid)
    assert kill.call_args_list == []
