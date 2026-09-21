"""Coverage tests for ai_governance.frugality.cli."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from ai_governance.frugality import cli


def test_fcntl_import_fallback_sets_module_attribute_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `fcntl` cannot be imported (non-POSIX), the module falls back to None."""
    import builtins
    import importlib

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "fcntl":
            raise ImportError("no fcntl on this platform")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        module = importlib.reload(cli)
        assert module.fcntl is None
    finally:
        # Undo the __import__ patch first so the restoring reload uses a real import.
        monkeypatch.undo()
        importlib.reload(cli)


def test_load_config_merges_existing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    (tmp_path / "frugal.json").write_text(json.dumps({"umbral_chars": 999}), encoding="utf-8")
    cfg = cli.load_config()
    assert cfg["umbral_chars"] == 999
    assert cfg["min_lineas_listado"] == cli.DEFAULT_CONFIG["min_lineas_listado"]


def test_load_config_ignores_malformed_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    (tmp_path / "frugal.json").write_text("not json", encoding="utf-8")
    cfg = cli.load_config()
    assert cfg == cli.DEFAULT_CONFIG


def test_load_config_no_file_returns_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    cfg = cli.load_config()
    assert cfg == cli.DEFAULT_CONFIG


def test_atomic_output_copy_returns_none_on_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no space left")

    monkeypatch.setattr(Path, "mkdir", boom)
    result = cli._atomic_output_copy(tmp_path, "id", "data")
    assert result is None


def test_atomic_output_copy_cleans_temp_on_replace_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(self: Path, _dest: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", boom)
    result = cli._atomic_output_copy(tmp_path, "id", "data")
    assert result is None
    assert list((tmp_path / "outputs").iterdir()) == []


def test_audit_trim_swallows_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", boom)
    # Must not raise.
    cli._audit_trim(tmp_path, "some command", 100, 50)


def test_audit_trim_without_fcntl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When fcntl is unavailable, locking is skipped but the audit line is still written."""
    monkeypatch.setattr(cli, "fcntl", None)
    cli._audit_trim(tmp_path, "some command", 100, 50)
    lines = (tmp_path / "trim-audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["original_chars"] == 100
    assert record["trimmed_chars"] == 50


def test_run_pre_bash_malformed_stdin_returns_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    cli.run_pre_bash({})
    assert capsys.readouterr().out == ""


def test_run_post_bash_malformed_stdin_returns_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    cli.run_post_bash({})
    assert capsys.readouterr().out == ""


def test_run_post_bash_skips_nofrugal_marker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"tool_input": {"command": "cat huge.json #nofrugal"}, "tool_output": "x" * 5000}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(cli.DEFAULT_CONFIG)
    assert capsys.readouterr().out == ""


def test_run_post_bash_skips_when_frugal_env_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FRUGAL", "0")
    payload = {"tool_input": {"command": "cat huge.json"}, "tool_output": "x" * 5000}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(cli.DEFAULT_CONFIG)
    assert capsys.readouterr().out == ""


def test_run_post_bash_returns_when_stdout_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"tool_input": {"command": "true"}, "tool_output": ""}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(cli.DEFAULT_CONFIG)
    assert capsys.readouterr().out == ""


def test_run_post_bash_returns_when_under_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"tool_input": {"command": "echo hi"}, "tool_output": "short"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(cli.DEFAULT_CONFIG)
    assert capsys.readouterr().out == ""


def test_run_post_bash_skips_git_diff_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"tool_input": {"command": "git diff HEAD~1"}, "tool_output": "x" * 20000}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(cli.DEFAULT_CONFIG)
    assert capsys.readouterr().out == ""


def test_run_post_bash_non_test_candidate_none_returns_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Large, non-homogeneous, non-JSON stdout produces no trim candidate."""
    big_text = "\n".join(f"totally distinct line {i} zzz" for i in range(5)) + "x" * 20000
    payload = {"tool_input": {"command": "echo assorted"}, "tool_output": big_text}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(cli.DEFAULT_CONFIG)
    assert capsys.readouterr().out == ""


_LISTING_CFG = {
    "umbral_chars": 500,
    "min_lineas_listado": 50,
    "prefijo_homogeneo_pct": 0.7,
    "head_lineas": 5,
    "tail_lineas": 5,
    "test_umbral_chars": 200,
    "test_head_lineas": 2,
    "test_tail_lineas": 3,
    "test_contexto_antes": 2,
    "test_contexto_despues": 5,
}


def test_run_post_bash_trims_non_test_listing_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Homogeneous non-test listing output goes through OutputTrimmer.trim_listing."""
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    lines = [f"/src/components/item_{i:03d}.tsx" for i in range(300)]
    payload = {
        "tool_input": {"command": "find /src -name '*.tsx'"},
        "tool_output": "\n".join(lines),
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(_LISTING_CFG)
    out = capsys.readouterr().out
    data = json.loads(out)
    updated = data["hookSpecificOutput"]["updatedToolOutput"]
    assert "lines omitted for frugality" in updated
    assert "full output:" in updated


def test_run_post_bash_dict_response_without_persisted_path_adds_generated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """When tool_response is a dict without persistedOutputPath, one is generated and included."""
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    lines = [f"/src/components/item_{i:03d}.tsx" for i in range(300)]
    payload = {
        "tool_input": {"command": "find /src -name '*.tsx'"},
        "tool_response": {"stdout": "\n".join(lines)},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(_LISTING_CFG)
    out = capsys.readouterr().out
    data = json.loads(out)
    updated = data["hookSpecificOutput"]["updatedToolOutput"]
    assert isinstance(updated, dict)
    assert "persistedOutputPath" in updated
    generated = list((tmp_path / "outputs").glob("*.txt"))
    assert len(generated) == 1


def test_run_post_bash_dict_response_persist_failure_omits_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """When generating a persisted copy fails, the updated response has no persistedOutputPath."""
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "_atomic_output_copy", lambda *_a, **_kw: None)
    lines = [f"/src/components/item_{i:03d}.tsx" for i in range(300)]
    payload = {
        "tool_input": {"command": "find /src -name '*.tsx'"},
        "tool_response": {"stdout": "\n".join(lines)},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cli.run_post_bash(_LISTING_CFG)
    out = capsys.readouterr().out
    data = json.loads(out)
    updated = data["hookSpecificOutput"]["updatedToolOutput"]
    assert isinstance(updated, dict)
    assert "persistedOutputPath" not in updated


def test_run_post_bash_new_output_not_smaller_returns_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """If the reference-augmented trim is not actually smaller, nothing is emitted."""
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    lines = [f"/src/components/item_{i:03d}.tsx" for i in range(300)]
    stdout = "\n".join(lines)
    payload = {
        "tool_input": {"command": "find /src -name '*.tsx'"},
        "tool_output": stdout,
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    call_count = {"n": 0}
    from ai_governance.frugality.output_trimmer import OutputTrimmer

    real_trim = OutputTrimmer.trim_listing

    def fake_trim(cls_stdout: str, cfg: dict, reference: str = "") -> str | None:
        call_count["n"] += 1
        if reference:
            # Simulate a trim result that is not actually shorter than the original.
            return stdout + "0"
        return real_trim(stdout, cfg, reference)

    monkeypatch.setattr(OutputTrimmer, "trim_listing", staticmethod(fake_trim))
    cli.run_post_bash(_LISTING_CFG)
    assert capsys.readouterr().out == ""


def test_main_post_bash_dispatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    payload = {"tool_input": {"command": "echo hi"}, "tool_output": "short"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, "argv", ["frugal", "--post-bash"])
    assert cli.main() == 0


def test_main_pre_bash_dispatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "get_runtime_dir", lambda: tmp_path)
    payload = {"tool_input": {"command": "cat package-lock.json"}, "session_id": "s1"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["--pre-bash"]) == 0
    out = capsys.readouterr().out
    assert "hookSpecificOutput" in out


def test_main_no_args_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "SpecOps Frugal Context Optimizer" in out
    assert "Usage: frugal --post-bash | frugal --pre-bash" in out


def test_main_swallows_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_cfg: dict) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "run_pre_bash", boom)
    result = cli.main(["--pre-bash"])
    assert result == 0
    err = capsys.readouterr().err
    assert "RuntimeError" in err


def test_main_uses_sys_argv_when_argv_is_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["frugal"])
    assert cli.main(None) == 0
    out = capsys.readouterr().out
    assert "SpecOps Frugal Context Optimizer" in out
