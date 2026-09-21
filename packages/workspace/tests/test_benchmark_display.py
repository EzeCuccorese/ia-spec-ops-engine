"""
Unit tests for workspace_engine.services.benchmark_display.
"""

import io
import json
import signal
import time
from unittest.mock import MagicMock, patch

from rich.console import Console
from workspace_engine.services import benchmark_display as bd


def _console():
    return Console(file=io.StringIO(), force_terminal=False, width=120)


def _render(renderable) -> str:
    c = _console()
    c.print(renderable)
    return c.file.getvalue()


# ---------------------------------------------------------------------------
# _detect_type
# ---------------------------------------------------------------------------


def test_detect_type_no_workspace_dir():
    bd._WORKSPACE_DIR = ""
    assert bd._detect_type("anything") == ""


def test_detect_type_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("does-not-exist") == ""


def test_detect_type_gradlew(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "gradlew").write_text("")
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "gradle"


def test_detect_type_build_gradle(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "build.gradle").write_text("")
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "gradle"


def test_detect_type_maven(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "pom.xml").write_text("")
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "maven"


def test_detect_type_go(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "go.mod").write_text("")
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "go"


def test_detect_type_next(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"dependencies": {"next": "1.0"}}))
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "next"


def test_detect_type_vite(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"devDependencies": {"vite": "1.0"}}))
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "vite"


def test_detect_type_node(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"dependencies": {"express": "1.0"}}))
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "node"


def test_detect_type_node_invalid_json(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    (d / "package.json").write_text("{not json")
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "node"


def test_detect_type_unknown(tmp_path, monkeypatch):
    d = tmp_path / "repositories" / "r1"
    d.mkdir(parents=True)
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", str(tmp_path))
    assert bd._detect_type("r1") == "?"


# ---------------------------------------------------------------------------
# _friendly_status / _fmt_*
# ---------------------------------------------------------------------------


def test_friendly_status_known_and_unknown():
    assert bd._friendly_status("green") == "passed"
    assert bd._friendly_status("weird") == "weird"
    assert bd._friendly_status("") == ""


def test_fmt_elapsed():
    assert bd._fmt_elapsed(0) == "00:00:00"
    assert bd._fmt_elapsed(3661) == "01:01:01"


def test_fmt_phase_elapsed_under_hour():
    assert bd._fmt_phase_elapsed(65) == "01:05"


def test_fmt_phase_elapsed_over_hour():
    assert bd._fmt_phase_elapsed(3700) == "1h01:40"


def test_fmt_secs_py_valid():
    assert bd._fmt_secs_py(65) == "01:05"
    assert bd._fmt_secs_py("65") == "01:05"


def test_fmt_secs_py_zero_and_none():
    assert bd._fmt_secs_py(0) == ""
    assert bd._fmt_secs_py(None) == ""


def test_fmt_secs_py_invalid():
    assert bd._fmt_secs_py("not-a-number") == ""


def test_fmt_gross_net_empty():
    assert bd._fmt_gross_net("", 10) == ""


def test_fmt_gross_net_no_gross_or_equal():
    assert bd._fmt_gross_net("✅ 01:00", 0) == "✅ 01:00"
    assert bd._fmt_gross_net("✅ 01:00", 60) == "✅ 01:00"


def test_fmt_gross_net_differs():
    result = bd._fmt_gross_net("✅ 01:00", 90)
    assert result == "✅ 01:30 (01:00)"


def test_fmt_gross_net_no_prefix():
    result = bd._fmt_gross_net("01:00", 90)
    assert result == "01:30 (01:00)"


# ---------------------------------------------------------------------------
# _sorted_repos / _select_visible
# ---------------------------------------------------------------------------


def test_sorted_repos_ordering():
    repos = ["a", "b", "c", "d"]
    statuses = {
        "a": {"status": "pending"},
        "b": {"status": "running", "repo_start_epoch": 5},
        "c": {"status": "green", "_done_epoch": 1},
        "d": {"status": "red_code", "_done_epoch": 2},
    }
    ordered = bd._sorted_repos(repos, statuses)
    assert ordered == ["c", "d", "b", "a"]


def test_select_visible_no_truncation():
    ordered = ["a", "b"]
    visible, hidden = bd._select_visible(ordered, {}, keep=5)
    assert visible == ordered
    assert hidden == 0


def test_select_visible_truncates():
    ordered = [f"r{i}" for i in range(10)]
    statuses = {
        "r0": {"status": "running"},
        "r1": {"status": "running"},
        "r2": {"status": "green"},
        "r3": {"status": "red_code"},
        "r4": {"status": "pending"},
        "r5": {"status": "pending"},
        "r6": {"status": "pending"},
        "r7": {"status": "pending"},
        "r8": {"status": "pending"},
        "r9": {"status": "pending"},
    }
    visible, hidden = bd._select_visible(ordered, statuses, keep=3)
    assert len(visible) == 3
    assert hidden == len(ordered) - 3
    # Order preserved relative to `ordered`.
    assert visible == [r for r in ordered if r in set(visible)]


# ---------------------------------------------------------------------------
# build_table
# ---------------------------------------------------------------------------


def test_build_table_pending_row(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    table = bd.build_table(["repo-a"], {}, repeat=False)
    out = _render(table)
    assert "repo-a" in out
    assert "pending" in out


def test_build_table_running_row_with_phase(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    statuses = {
        "repo-a": {
            "status": "running",
            "repo_start_epoch": time.time() - 5,
            "phase": "install",
            "phase_start_epoch": time.time() - 2,
        }
    }
    table = bd.build_table(["repo-a"], statuses, repeat=True)
    out = _render(table)
    assert "repo-a" in out
    assert "running" in out


def test_build_table_running_row_all_phases(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    for phase in ("pre_install", "build", "pre_cold", "cold_tests", "pre_warm", "warm"):
        statuses = {
            "repo-a": {
                "status": "running",
                "repo_start_epoch": time.time() - 1,
                "phase": phase,
                "phase_start_epoch": time.time() - 1,
            }
        }
        table = bd.build_table(["repo-a"], statuses, repeat=True)
        out = _render(table)
        assert "repo-a" in out


def test_build_table_running_row_no_start_no_phase(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    statuses = {"repo-a": {"status": "running"}}
    table = bd.build_table(["repo-a"], statuses, repeat=False)
    out = _render(table)
    assert "repo-a" in out


def test_build_table_done_row_green(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    statuses = {
        "repo-a": {
            "status": "green",
            "tests": "5",
            "pre_install": "00:01",
            "install": "01:00",
            "install_wall": 70,
            "build": "00:05",
            "pre_cold": "00:01",
            "cold": "02:00",
            "cold_wall": 130,
            "pre_warm": "00:01",
            "warm": "01:30",
            "warm_wall": 100,
            "total": "05:00",
            "finish_time": "12:00:00",
        }
    }
    table = bd.build_table(["repo-a"], statuses, repeat=True)
    out = _render(table)
    assert "repo-a" in out
    assert "passed" in out


def test_build_table_hidden_row_with_pending(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    repos = [f"r{i}" for i in range(6)]
    statuses = {
        "r0": {"status": "running"},
        "r1": {"status": "green", "_done_epoch": 1},
        "r2": {"status": "pending"},
        "r3": {"status": "pending"},
        "r4": {"status": "pending"},
        "r5": {"status": "pending"},
    }
    table = bd.build_table(repos, statuses, repeat=False, max_rows=3)
    out = _render(table)
    assert "more" in out
    assert "pending)" in out


def test_build_table_hidden_row_no_pending(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    repos = [f"r{i}" for i in range(6)]
    statuses = {r: {"status": "green", "_done_epoch": i} for i, r in enumerate(repos)}
    table = bd.build_table(repos, statuses, repeat=False, max_rows=3)
    out = _render(table)
    assert "more" in out


def test_build_table_row_icon_override(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    statuses = {"repo-a": {"status": "pending", "row_icon": "X", "type": "cust"}}
    table = bd.build_table(["repo-a"], statuses, repeat=False)
    out = _render(table)
    assert "cust" in out


# ---------------------------------------------------------------------------
# LiveDisplay
# ---------------------------------------------------------------------------


def test_live_display_rich_console(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    display = bd.LiveDisplay(
        repos=["repo-a", "repo-b"],
        statuses={"repo-a": {"status": "green"}},
        repeat=False,
        start_time=time.monotonic() - 3,
        parallel=2,
    )
    out = _render(display)
    assert "repo-a" in out
    assert "repo-b" in out
    assert "parallel=2" in out
    assert "mode=single" in out


def test_live_display_repeat_mode(monkeypatch):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    display = bd.LiveDisplay(
        repos=["repo-a"],
        statuses={},
        repeat=True,
        start_time=time.monotonic(),
        parallel=1,
    )
    out = _render(display)
    assert "mode=repeat" in out


# ---------------------------------------------------------------------------
# run_final
# ---------------------------------------------------------------------------


def test_run_final_missing_file(tmp_path, capsys):
    missing = tmp_path / "nope.tsv"
    try:
        bd.run_final(str(missing))
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expected SystemExit")


def test_run_final_full_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    summary = tmp_path / "summary.tsv"
    header = "repo\texit\tstatus\tinstall\tbuild\tcold\twarm\ttotal\tcold_tests\twarm_tests\twarm_icon\tcold_icon\trow_icon\n"
    elapsed_line = "#elapsed\t00:05:00\n"
    row_green = (
        "repo-a\t0\tgreen\t60\t5\t120\t90\t300\t5 passed\t5 passed\t✅\t✅\t✅"
        "\tnote-a\t1\t2\t3\t65\t125\t95\n"
    )
    row_short = "repo-b\t0\tred_code\t0\t0\t0\t0\t0\t0\t0\t\t\t\n"
    summary.write_text(header + elapsed_line + row_green + row_short)

    def plain_console(*args, **kwargs):
        kwargs["force_terminal"] = False
        kwargs["color_system"] = None
        return Console(*args, **kwargs)

    with patch.object(bd, "Console", side_effect=plain_console):
        bd.run_final(str(summary))
    out = capsys.readouterr().out
    assert "repo-a" in out
    assert "RESULT" in out
    assert "time=00:05:00" in out


def test_run_final_elapsed_arg_overrides(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    summary = tmp_path / "summary.tsv"
    header = "repo\texit\tstatus\tinstall\tbuild\tcold\twarm\ttotal\tcold_tests\twarm_tests\twarm_icon\tcold_icon\trow_icon\n"
    row = "repo-a\t0\tno_tests\t0\t0\t0\t0\t0\t0\t0\t\t\t0️⃣\n"
    summary.write_text(header + row)

    def plain_console(*args, **kwargs):
        kwargs["force_terminal"] = False
        kwargs["color_system"] = None
        return Console(*args, **kwargs)

    with patch.object(bd, "Console", side_effect=plain_console):
        bd.run_final(str(summary), elapsed="00:10:00")
    out = capsys.readouterr().out
    assert "time=00:10:00" in out


def test_run_final_skips_blank_and_short_lines(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bd, "_WORKSPACE_DIR", "")
    summary = tmp_path / "summary.tsv"
    summary.write_text("\ntoo\tshort\n")
    bd.run_final(str(summary))
    out = capsys.readouterr().out
    assert "RESULT" in out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_no_repos_exits(monkeypatch):
    monkeypatch.setattr("sys.argv", ["benchmark_display.py"])
    try:
        bd.main()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit")


def test_main_final_mode_missing_summary(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["benchmark_display.py", "--final"])
    try:
        bd.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expected SystemExit")
    err = capsys.readouterr().err
    assert "Usage:" in err


def test_main_final_mode_with_summary(monkeypatch, tmp_path):
    summary = tmp_path / "summary.tsv"
    header = "repo\texit\tstatus\tinstall\tbuild\tcold\twarm\ttotal\tcold_tests\twarm_tests\twarm_icon\tcold_icon\trow_icon\n"
    row = "repo-a\t0\tgreen\t0\t0\t0\t0\t0\t0\t0\t\t\t✅\n"
    summary.write_text(header + row)
    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark_display.py",
            "--workspace-dir",
            str(tmp_path),
            "--final",
            str(summary),
            "--elapsed",
            "00:01:00",
        ],
    )
    with patch.object(bd, "run_final") as mock_run_final:
        bd.main()
    mock_run_final.assert_called_once_with(str(summary), "00:01:00")


def test_main_final_mode_flag_without_path(monkeypatch, tmp_path):
    """--final followed by another flag (no positional summary path) hits the
    'else' branch that leaves summary_path unset, then exits with usage."""
    monkeypatch.setattr("sys.argv", ["benchmark_display.py", "--final", "--elapsed", "00:00:01"])
    try:
        bd.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expected SystemExit")


def test_main_parallel_default_and_explicit(monkeypatch):
    """--parallel without a following value falls back to default 4."""
    monkeypatch.setattr("sys.argv", ["benchmark_display.py", "--parallel"])
    try:
        bd.main()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit")


def test_main_elapsed_without_value(monkeypatch):
    monkeypatch.setattr("sys.argv", ["benchmark_display.py", "--elapsed"])
    try:
        bd.main()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit")


def test_main_live_loop_processes_messages_and_done(monkeypatch):
    lines = [
        json.dumps({"repo": "repo-a", "status": "running"}),
        "",
        "not-json{",
        json.dumps({"repo": "not-in-list", "status": "green"}),
        json.dumps({"repo": "repo-a", "status": "green"}),
        json.dumps(
            {"done": True, "green": 1, "red": 0, "infra": 0, "no_tests": 0, "elapsed_secs": 3}
        ),
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    monkeypatch.setattr("sys.argv", ["benchmark_display.py", "repo-a", "--repeat"])
    monkeypatch.setattr(signal, "signal", lambda *a, **k: None)

    fake_live = MagicMock()
    fake_live.__enter__ = MagicMock(return_value=fake_live)
    fake_live.__exit__ = MagicMock(return_value=False)

    with patch.object(bd, "Live", return_value=fake_live):
        bd.main()


def test_main_live_loop_without_done_message(monkeypatch):
    lines = [json.dumps({"repo": "repo-a", "status": "green"})]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    monkeypatch.setattr("sys.argv", ["benchmark_display.py", "repo-a"])
    monkeypatch.setattr(signal, "signal", lambda *a, **k: None)

    fake_live = MagicMock()
    fake_live.__enter__ = MagicMock(return_value=fake_live)
    fake_live.__exit__ = MagicMock(return_value=False)

    with patch.object(bd, "Live", return_value=fake_live):
        bd.main()
