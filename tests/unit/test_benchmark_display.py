import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "btdisplay",
    os.path.join(os.path.dirname(__file__), "..", "..", "devscripts", "services", "unit_test_benchmark_display.py"),
)
btdisplay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(btdisplay)


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch):
    # run_final/build_table size the table from shutil.get_terminal_size, which honors
    # COLUMNS. CI runners report a narrow width (~80), truncating later columns (PRE-C,
    # etc.) to "…" and breaking assertions on rendered values. Pin a wide, deterministic
    # width so the full table renders regardless of the ambient terminal.
    monkeypatch.setenv("COLUMNS", "240")


def _write_summary(tmp_path):
    header = ("repo\texit_code\tstatus\tinstall_secs\tbuild_secs\tcold_secs\t"
              "warm_secs\ttotal_secs\tcold_tests\twarm_tests\twarm_icon\t"
              "cold_icon\trow_icon\tnote\tpre_install_secs\tpre_cold_secs\tpre_warm_secs\t"
              "install_wall_secs\tcold_wall_secs\twarm_wall_secs\n")
    row = ("myrepo\t0\tgreen\t60\t0\t30\t0\t180\t5/5\t\t\t✅\t✅\t"
           "All tests passed\t10\t75\t0\t116\t45\t0\n")
    p = tmp_path / "summary.tsv"
    p.write_text(header + row)
    return str(p)


def test_build_table_has_pre_columns():
    statuses = {"myrepo": {"status": "green", "pre_install": "00:10",
                           "pre_cold": "01:15", "pre_warm": ""}}
    t = btdisplay.build_table(["myrepo"], statuses, repeat=False)
    headers = [c.header for c in t.columns]
    assert "PRE-I" in headers
    assert "PRE-C" in headers
    assert headers.index("PRE-I") < headers.index("INSTALL")
    assert headers.index("PRE-C") < headers.index("COLD")


def test_status_column_last_and_friendly_no_note_column():
    # STATUS moved to the very end with a terse friendly label; the NOTE column is gone
    # from the TUI (it lives only in summary.tsv). The verbose note must not be rendered.
    statuses = {"r": {"status": "green", "row_icon": "✅", "type": "node",
                      "tests": "5/5", "total": "01:00",
                      "note": "All tests passed (cold+warm)"}}
    t = btdisplay.build_table(["r"], statuses, repeat=False)
    headers = [c.header for c in t.columns]
    assert "NOTE" not in headers, "NOTE column must not appear in the TUI"
    assert headers[-1] == "STATUS", f"STATUS must be the last column, headers={headers}"
    # TYPE must be immediately followed by TESTS (the old STATUS-after-TYPE slot is gone).
    assert headers[headers.index("TYPE") + 1] == "TESTS"
    cells = {c.header: list(c.cells)[0].plain for c in t.columns}
    assert cells["STATUS"] == "passed", cells["STATUS"]
    # The verbose note text appears nowhere in the rendered TUI.
    assert all("All tests passed" not in v for v in cells.values())


def test_finished_row_empty_build_renders_empty_not_placeholder():
    # A finished repo with no build phase (build_secs=0 → build="") must show an empty
    # BUILD cell, not a "--:--" placeholder.
    statuses = {"r": {"status": "green", "row_icon": "✅", "type": "next",
                      "tests": "5/5", "total": "01:00", "build": ""}}
    t = btdisplay.build_table(["r"], statuses, repeat=False)
    cells = {c.header: list(c.cells)[0].plain for c in t.columns}
    assert cells["BUILD"] == "", f"BUILD must be empty, got {cells['BUILD']!r}"


def test_finished_row_shows_build_time_when_present():
    statuses = {"r": {"status": "green", "row_icon": "✅", "type": "next",
                      "tests": "5/5", "total": "01:00", "build": "00:04"}}
    t = btdisplay.build_table(["r"], statuses, repeat=False)
    cells = {c.header: list(c.cells)[0].plain for c in t.columns}
    assert cells["BUILD"] == "00:04", cells["BUILD"]


def test_friendly_status_mapping():
    assert btdisplay._friendly_status("green") == "passed"
    assert btdisplay._friendly_status("red_code") == "tests failed"
    assert btdisplay._friendly_status("red_infra") == "infra error"
    assert btdisplay._friendly_status("no_tests") == "no tests"
    assert btdisplay._friendly_status("running") == "running"


def test_run_final_parses_pre_columns(tmp_path, capsys):
    btdisplay._WORKSPACE_DIR = ""
    path = _write_summary(tmp_path)
    btdisplay.run_final(path)
    out = capsys.readouterr().out
    # 75s pre-cold renders as 01:15 in the final table
    assert "01:15" in out
    # install gross 116s renders as the (01:56) parenthetical next to net 01:00
    assert "01:56" in out


def test_run_final_renders_docker_context_from_tsv(tmp_path, capsys):
    btdisplay._WORKSPACE_DIR = ""
    header = ("repo\texit_code\tstatus\tinstall_secs\tbuild_secs\tcold_secs\t"
              "warm_secs\ttotal_secs\tcold_tests\twarm_tests\twarm_icon\t"
              "cold_icon\trow_icon\tnote\tpre_install_secs\tpre_cold_secs\tpre_warm_secs\t"
              "install_wall_secs\tcold_wall_secs\twarm_wall_secs\n")
    row = ("myrepo\t0\tgreen\t60\t0\t30\t0\t180\t5/5\t\t\t✅\t✅\t"
           "ok\t10\t75\t0\t116\t45\t0\n")
    p = tmp_path / "summary.tsv"
    p.write_text(header + row + "#docker\torbstack\n")
    btdisplay.run_final(str(p))
    out = capsys.readouterr().out
    assert "docker=orbstack" in out


def test_live_display_header_shows_docker_context():
    statuses = {"r": {"status": "running"}}
    d = btdisplay.LiveDisplay(["r"], statuses, repeat=False, start_time=0.0,
                              parallel=4, docker_context="colima")
    from rich.console import Console
    buf = Console(width=200)
    with buf.capture() as cap:
        buf.print(d)
    out = cap.get()
    assert "docker=colima" in out


def test_gross_net_formats_gross_then_net():
    # install: net 01:00, gross 116s → "01:56 (01:00)" (gross leads)
    assert btdisplay._fmt_gross_net("01:00", 116) == "01:56 (01:00)"
    # cold/warm carry an icon; icon is preserved, gross leads, net in parens
    assert btdisplay._fmt_gross_net("✅ 00:30", 45) == "✅ 00:45 (00:30)"


def test_gross_net_skips_when_equal_or_missing():
    assert btdisplay._fmt_gross_net("01:00", 60) == "01:00"   # gross == net → no parens
    assert btdisplay._fmt_gross_net("01:00", 0) == "01:00"    # gross unknown
    assert btdisplay._fmt_gross_net("", 116) == ""            # no net → nothing


def test_finished_row_shows_gross_net_for_install_cold():
    statuses = {"myrepo": {
        "status": "green", "row_icon": "✅", "type": "node",
        "install": "01:00", "install_wall": "116",
        "cold": "✅ 00:30", "cold_wall": "45",
        "total": "03:00", "tests": "5/5", "note": "",
    }}
    t = btdisplay.build_table(["myrepo"], statuses, repeat=False)
    cells = {c.header: list(c.cells)[0].plain for c in t.columns}
    assert cells["INSTALL"] == "01:56 (01:00)", cells["INSTALL"]
    assert cells["COLD"] == "✅ 00:45 (00:30)", cells["COLD"]


def test_running_row_shows_gross_net_for_completed_phase():
    # A running repo whose INSTALL phase just completed must already show "gross (net)"
    # (not just net), and COLD frozen likewise — same as finished rows.
    statuses = {"r": {
        "status": "running", "type": "node", "repo_start_epoch": 0,
        "phase": "cold_tests", "phase_start_epoch": 0,
        "install": "01:00", "install_wall": "116",
        "cold": "✅ 00:30", "cold_wall": "45",
    }}
    t = btdisplay.build_table(["r"], statuses, repeat=False)
    cells = {c.header: list(c.cells)[0].plain for c in t.columns}
    assert cells["INSTALL"] == "01:56 (01:00)", cells["INSTALL"]
    assert cells["COLD"] == "✅ 00:45 (00:30)", cells["COLD"]


def test_build_table_repeat_mode_pre_warm_column_and_no_overflow_crash():
    """PRE-W column present in repeat mode; overflow row must not raise ValueError."""
    repos = [f"repo{i}" for i in range(5)]
    statuses = {
        r: {
            "status": "green",
            "pre_install": "00:05",
            "pre_cold": "00:10",
            "pre_warm": "00:03",
            "install": "01:00",
            "build": "00:04",
            "cold": "✅ 00:30",
            "warm": "✅ 00:20",
            "total": "02:00",
            "finish_time": "12:00:00",
            "tests": "10/10",
            "note": "",
        }
        for r in repos
    }

    # Verify PRE-W column is present and ordered before WARM.
    t_full = btdisplay.build_table(repos, statuses, repeat=True)
    headers = [c.header for c in t_full.columns]
    assert "PRE-W" in headers, "PRE-W column must exist in repeat mode"
    assert headers.index("PRE-W") < headers.index("WARM"), "PRE-W must precede WARM"

    # Force an overflow row (max_rows=2 with 5 repos → "+N más" row emitted).
    # This is the case that triggered C1: a mismatched ncells caused Rich to auto-add
    # an extra unnamed column. Repeat mode has 15 columns (STATUS moved to the end and
    # the NOTE column was dropped from the TUI — note lives only in summary.tsv).
    t_overflow = btdisplay.build_table(repos, statuses, repeat=True, max_rows=2)
    overflow_col_count = len(list(t_overflow.columns))
    assert overflow_col_count == 15, (
        f"overflow table must have exactly 15 columns in repeat mode, got {overflow_col_count}"
    )


def _running_cells(phase, extra=None):
    """build_table for one running repo in `phase`; return {header: first-cell-text}."""
    s = {"status": "running", "type": "node", "phase": phase,
         "phase_start_epoch": 1.0, "repo_start_epoch": 1.0}
    if extra:
        s.update(extra)
    t = btdisplay.build_table(["r"], {"r": s}, repeat=False)
    return {c.header: list(c.cells)[0].plain for c in t.columns}


def test_running_spinner_lands_in_pre_install_column():
    """At startup (pre_install phase) the live spinner is under PRE-I, not INSTALL."""
    cells = _running_cells("pre_install")
    assert cells["PRE-I"].startswith("🔄"), f"PRE-I should show spinner, got {cells['PRE-I']!r}"
    assert cells["INSTALL"] == "", f"INSTALL must be empty during pre_install, got {cells['INSTALL']!r}"


def test_running_spinner_moves_to_install_and_freezes_pre_install():
    """Once install begins, the spinner is under INSTALL and PRE-I shows its frozen value."""
    cells = _running_cells("install", {"pre_install": "00:01"})
    assert cells["PRE-I"] == "00:01", f"PRE-I should be frozen, got {cells['PRE-I']!r}"
    assert cells["INSTALL"].startswith("🔄"), f"INSTALL should show spinner, got {cells['INSTALL']!r}"


def test_running_spinner_lands_in_pre_cold_column():
    """During post-install setup (pre_cold phase) the spinner is under PRE-C, not COLD."""
    cells = _running_cells("pre_cold", {"pre_install": "00:01", "install": "01:00"})
    assert cells["PRE-C"].startswith("🔄"), f"PRE-C should show spinner, got {cells['PRE-C']!r}"
    assert cells["COLD"] == "", f"COLD must be empty during pre_cold, got {cells['COLD']!r}"
