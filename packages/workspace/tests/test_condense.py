import io
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from workspace_engine.common.subprocess import DEFAULT_COMMAND_TIMEOUT
from workspace_engine.condense import cli, logs
from workspace_engine.condense.engine import clean_lines, condense, dedupe, profile_for


@pytest.fixture(autouse=True)
def _log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_LOG_DIR", str(tmp_path / "logs"))


def _pytest_failure_output() -> str:
    lines = ["============================= test session starts =============================="]
    lines += [
        f"tests/test_mod{i}.py ........................................ [{i}%]" for i in range(80)
    ]
    lines += [
        "=================================== FAILURES ===================================",
        "________________________________ test_total ____________________________________",
        "    def test_total():",
        ">       assert total([1, 2]) == 4",
        "E       assert 3 == 4",
        "tests/test_math.py:12: AssertionError",
    ]
    lines += [
        f"tests/test_more{i}.py ......................................... [{i}%]" for i in range(80)
    ]
    lines += [
        "FAILED tests/test_math.py::test_total - assert 3 == 4",
        "========================= 1 failed, 812 passed in 4.21s =========================",
    ]
    return "\n".join(lines)


def test_error_in_the_middle_survives_and_output_shrinks() -> None:
    text = _pytest_failure_output()
    result = condense(text, "uv run pytest -q", exit_code=1, budget=1500)
    assert result.tool == "pytest"
    assert result.truncated
    assert len(result.text) <= 1500
    assert len(result.text) < len(text) / 4
    for needle in ("E       assert 3 == 4", "tests/test_math.py:12", "1 failed, 812 passed"):
        assert needle in result.text


def test_success_collapses_to_one_line() -> None:
    text = _pytest_failure_output().replace("1 failed, ", "")
    result = condense(text, "pytest", exit_code=0, budget=500)
    assert result.text.startswith("✓ pytest:")
    assert "812 passed" in result.text
    assert "\n" not in result.text


def test_small_output_is_kept_verbatim_without_ansi() -> None:
    result = condense("\x1b[31mhello\x1b[0m\nworld", "echo", exit_code=1)
    assert result.text == "hello\nworld"
    assert not result.truncated


def test_generic_failure_keeps_error_context() -> None:
    noise = [f"INFO processing record {i} of 5000" for i in range(400)]
    text = "\n".join(noise[:200] + ["ERROR: connection refused to db:5432"] + noise[200:])
    result = condense(text, "./deploy.sh", exit_code=2, budget=1200)
    assert result.tool == "generic"
    assert "connection refused" in result.text
    assert "similar lines" in result.text or "omitted" in result.text


def test_clean_lines_drops_progress_and_carriage_returns() -> None:
    raw = "Downloading 10%\rDownloading 100%\n[=====>        ] 45%\n2026-09-23T10:00:00Z real line"
    assert clean_lines(raw) == ["real line"]


def test_dedupe_collapses_similar_lines() -> None:
    lines = [f"Compiling module {i} at 0x{i:04x}" for i in range(5)] + ["done"]
    assert dedupe(lines) == ["Compiling module 0 at 0x0000", "  … ×4 similar lines", "done"]


@pytest.mark.parametrize(
    ("command", "tool"),
    [
        ("npx vitest run", "jest"),
        ("go test ./...", "go"),
        ("cargo test", "cargo"),
        ("./mvnw verify", "maven-gradle"),
        ("npx tsc --noEmit", "lint"),
        ("ls -la", None),
    ],
)
def test_profile_detection(command, tool) -> None:
    profile = profile_for(command)
    assert (profile.name if profile else None) == tool


def test_ws_run_preserves_exit_code_and_saves_private_log(capsys) -> None:
    script = "for i in $(seq 1 400); do echo line $i; done; echo 'FATAL boom' >&2; exit 3"
    code = cli.run(["--budget", "600", "--", script])
    out = capsys.readouterr().out
    assert code == 3
    assert "FATAL boom" in out and "exit=3" in out
    log_id = out.rsplit("ws log ", 1)[1].split()[0]
    path = logs.logs_dir() / f"{log_id}.log"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "line 200" in logs.read(log_id, grep="line 200$")
    assert logs.read(log_id, lines="2-3").splitlines()[0].startswith("2: ")


def test_ws_condense_json_contract(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(_pytest_failure_output()))
    cli.condense_stdin(["--command", "pytest", "--exit-code", "1", "--json", "--budget", "900"])
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1 and payload["truncated"] and payload["log_id"]
    assert "assert 3 == 4" in payload["text"]


def test_log_store_is_pruned(monkeypatch) -> None:
    monkeypatch.setattr(logs, "MAX_LOGS", 2)
    ids = [logs.save(f"out {i}", "cmd") for i in range(3)]
    remaining = {p.stem for p in logs.logs_dir().glob("*.log")}
    assert len(remaining) == 2 and ids[-1] in remaining


def test_invalid_log_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        logs.read("../etc/passwd")
    assert os.sep not in "abc"


def test_condense_text_mode_prints_footer(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(_pytest_failure_output()))
    assert cli.condense_stdin(["--command", "pytest", "--exit-code", "1", "--budget", "900"]) == 0
    out = capsys.readouterr().out
    assert "assert 3 == 4" in out and "ws log " in out


def test_show_log_reports_errors_and_filters(capsys) -> None:
    assert cli.show_log(["deadbeef00"]) == 1
    assert "ERROR" in capsys.readouterr().err
    log_id = logs.save("alpha\nbeta\ngamma", "cmd")
    assert cli.show_log([log_id, "--grep", "beta"]) == 0
    assert capsys.readouterr().out.strip() == "3: beta"


def test_ws_run_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.run(["--"])


def test_ws_run_small_success_prints_output_without_log(capsys) -> None:
    assert cli.run(["--", "echo", "hello"]) == 0
    out = capsys.readouterr().out
    assert "hello" in out and "ws log" not in out and "exit=0" in out


def test_generic_success_keeps_structure_instead_of_one_line() -> None:
    listing = "\n".join(f"/usr/lib/dir{i}:\nfile_{i}.dylib" for i in range(400))
    result = condense(listing, "ls -R /usr/lib", exit_code=0, budget=1200)
    assert not result.text.startswith("✓")
    assert "/usr/lib/dir0:" in result.text and "omitted" in result.text
    assert len(result.text) <= 1200


def test_ws_log_last(capsys) -> None:
    logs.save("first", "a")
    last = logs.save("second\nERROR here", "b")
    assert cli.show_log(["--last", "--grep", "ERROR"]) == 0
    assert "ERROR here" in capsys.readouterr().out
    assert logs.latest() == last
    assert cli.show_log([]) == 1


def test_ws_run_timeout_returns_124_and_saves_truncated_partial_output(monkeypatch, capsys) -> None:
    partial_out = "\n".join(f"line {i}" for i in range(120)).encode("utf-8")
    partial_err = b"ERROR: stalled on step\xff"

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs["timeout"],
            output=partial_out,
            stderr=partial_err,
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code = cli.run(["--timeout", "3", "--budget", "300", "--", "sleep", "10"])
    captured = capsys.readouterr()

    assert code == 124
    assert "ERROR: command timed out after 3s: sleep 10" in captured.err
    assert "exit=124" in captured.out
    assert "ws log " in captured.out
    log_id = captured.out.rsplit("ws log ", 1)[1].split()[0]
    saved = logs.read(log_id)
    assert "line 0" in saved
    assert "stalled on step" in saved


def test_ws_run_timeout_handles_str_and_none_streams(monkeypatch, capsys) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs["timeout"],
            output="partial text",
            stderr=None,
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    code = cli.run(["--timeout", "2", "--", "echo", "hi"])
    captured = capsys.readouterr()

    assert code == 124
    assert "partial text" in captured.out
    assert "ws log" not in captured.out
    assert "exit=124" in captured.out
    assert "timed out after 2s" in captured.err


@pytest.mark.parametrize(
    ("extra_args", "expected_timeout"),
    [
        ([], DEFAULT_COMMAND_TIMEOUT),
        (["--timeout", "15"], 15),
        (["--timeout", "0"], None),
        (["--timeout", "-5"], None),
    ],
)
def test_ws_run_timeout_flag_values(monkeypatch, extra_args, expected_timeout) -> None:
    seen: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.run([*extra_args, "--", "echo", "ok"]) == 0
    assert seen["timeout"] == expected_timeout


def test_clean_lines_keeps_coverage_percentages_and_drops_progress() -> None:
    raw = (
        "Downloading 42%\n"
        "[=====>        ] 45%\n"
        "tests/test_a.py .... [ 50%]\n"
        "TOTAL                                  4500    200    95%\n"
        "Disk usage: 82%\n"
    )
    assert clean_lines(raw) == [
        "TOTAL                                  4500    200    95%",
        "Disk usage: 82%",
    ]


def test_condense_strictly_bounds_oversized_tail_lines() -> None:
    huge = "x" * 4000
    text = "\n".join(["ERROR: minified crash", huge, huge])
    result = condense(text, "npm run build", exit_code=1, budget=300)
    assert result.truncated
    assert len(result.text) <= 300


def test_condense_recognizes_pytest_quiet_summary_and_ws_check_profile() -> None:
    body = "\n".join(["." * 80 for _ in range(20)] + ["42 passed in 1.23s", "trailing note"])
    result = condense(body, "pytest -q", exit_code=0, budget=200)
    assert result.text == "✓ pytest: 42 passed in 1.23s"
    profile = profile_for("ws check --changed")
    assert profile is not None and profile.name == "ws-check"


def test_show_log_rejects_invalid_grep_regex_cleanly(capsys) -> None:
    log_id = logs.save("alpha\nbeta", "cmd")
    assert cli.show_log([log_id, "--grep", "[unclosed"]) == 1
    assert "Invalid grep regex" in capsys.readouterr().err


def test_condense_omits_trailing_noise_and_caps_many_failures() -> None:
    trailing = "\n".join(["ERROR: first failure"] + [f"trailing {i}" for i in range(40)])
    omitted = condense(trailing, "./run.sh", exit_code=1, budget=350)
    assert "ERROR: first failure" in omitted.text
    assert "lines omitted" in omitted.text

    many_errors = "\n".join(f"ERROR: {chr(65 + i) * 12} failed in subsystem" for i in range(20))
    capped = condense(many_errors, "./run.sh", exit_code=1, budget=250)
    assert len(capped.text) <= 250
    assert "more failures omitted" in capped.text


def test_condense_all_blank_lines_over_budget_returns_empty() -> None:
    result = condense("\n" * 120, "./run.sh", exit_code=1, budget=50)
    assert result.text == ""
    assert result.truncated


def test_logs_latest_empty_and_config_error_fallback(monkeypatch, tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="No saved logs"):
        logs.latest()

    cfg_dir = tmp_path / "repo" / ".workspace"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text("bad = [toml", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "repo")
    log_id = logs.save("hello", "echo hi")
    assert logs.latest() == log_id


def _is_process_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    _, _, rest = stat_text.rpartition(")")
    fields = rest.split()
    return bool(fields) and fields[0] in {"Z", "X"}


@pytest.mark.skipif(os.name != "posix", reason="process-group kill requires POSIX")
def test_ws_run_timeout_kills_process_group_and_grandchildren(tmp_path, capsys) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = (
        f'"{sys.executable}" -c "import time; time.sleep(60)" & '
        f'echo $! > "{pid_file}"; '
        'echo "PARTIAL_BEFORE_TIMEOUT"; '
        "wait"
    )
    code = cli.run(["--timeout", "1", "--", script])
    captured = capsys.readouterr()

    assert code == 124
    assert "PARTIAL_BEFORE_TIMEOUT" in captured.out
    assert "ERROR: command timed out after 1s" in captured.err
    grandchild_pid = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 2.0
    while not _is_process_gone(grandchild_pid):
        assert time.monotonic() < deadline, f"grandchild {grandchild_pid} still alive"
        time.sleep(0.02)


@pytest.mark.skipif(os.name != "posix", reason="SIGTERM/SIGKILL escalation requires POSIX")
def test_ws_run_timeout_escalates_to_sigkill_when_sigterm_ignored(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_TERM_GRACE_SECONDS", 0.1)
    script = "trap '' TERM; echo STUBBORN_OUTPUT; exec sleep 60"
    code = cli.run(["--timeout", "1", "--", script])
    captured = capsys.readouterr()

    assert code == 124
    assert "STUBBORN_OUTPUT" in captured.out
    assert "ERROR: command timed out after 1s" in captured.err


@pytest.mark.parametrize(
    ("fails_before_exit", "expected_events"),
    [
        (1, ["start_new_session=False", "terminate"]),
        (2, ["start_new_session=False", "terminate", "kill"]),
    ],
    ids=["exits-on-terminate", "escalates-to-kill"],
)
def test_ws_run_timeout_non_posix_fallback_terminates_and_kills(
    monkeypatch, capsys, fails_before_exit: int, expected_events: list[str]
) -> None:
    events: list[str] = []

    class FakePopen:
        pid = 99999
        returncode = -9

        def __init__(self, *args, **kwargs):
            events.append(f"start_new_session={kwargs.get('start_new_session')}")
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls <= fails_before_exit:
                raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 1)
            return ("partial-win", "")

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    code = cli.run(["--timeout", "1", "--", "echo", "hi"])
    captured = capsys.readouterr()

    assert code == 124
    assert "partial-win" in captured.out
    assert events == expected_events


def test_ws_run_preserves_exit_code_when_log_dir_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = tmp_path / "blocked-file"
    blocked.write_text("not a dir", encoding="utf-8")
    monkeypatch.setenv("WORKSPACE_LOG_DIR", str(blocked / "logs"))

    noise = "\n".join(f"line {i}" for i in range(80))
    code = cli.run(
        [
            "--budget",
            "150",
            "--",
            sys.executable,
            "-c",
            f"import sys; print({noise!r}); sys.exit(7)",
        ]
    )
    captured = capsys.readouterr()
    assert code == 7
    assert "WARNING: could not save full log" in captured.err
    assert "[exit=7" in captured.out

    timeout_code = cli.run(
        [
            "--budget",
            "150",
            "--timeout",
            "1",
            "--",
            sys.executable,
            "-c",
            f"import time; print({noise!r}, flush=True); time.sleep(10)",
        ]
    )
    timeout_captured = capsys.readouterr()
    assert timeout_code == 124
    assert "WARNING: could not save full log" in timeout_captured.err
    assert "[exit=124" in timeout_captured.out


def test_ws_run_caps_captured_output_in_memory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_MAX_CAPTURE_BYTES", 256)
    code = cli.run(
        [
            "--budget",
            "400",
            "--",
            sys.executable,
            "-c",
            "print('A' * 1024)",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "exit=0" in captured.out
