import io
import os
import stat
import sys

import pytest
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
