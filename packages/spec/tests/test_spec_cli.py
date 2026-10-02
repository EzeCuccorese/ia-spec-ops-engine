import json
import sys
from pathlib import Path

import pytest
from spec.agents import RECOGNIZED_AGENTS
from spec.cli import main, run_doctor, run_verify
from spec.core.result import CheckStatus
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import Stage, Workflow


def test_doctor_json_has_stable_contract(capsys) -> None:
    assert run_doctor(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["spec_version"]
    assert payload["python_version"]
    assert payload["platform"]


def test_verify_executes_config_and_records_workflow_evidence(tmp_path: Path, capsys) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    config = tmp_path / ".spec/verification.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "smoke",
                        "command": [sys.executable, "-c", "print('verified')"],
                    }
                ],
            }
        )
    )

    assert run_verify(tmp_path, as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    snapshot = workflow.status()
    assert payload["status"] == "PASS"
    assert snapshot is not None
    assert snapshot.stage is Stage.VERIFY
    assert snapshot.verification_status is CheckStatus.PASS


def test_cli_new_command_creates_specification(tmp_path: Path) -> None:
    import pytest
    from spec.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["new", "Direct Feature", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert (tmp_path / ".spec/specs/direct-feature/spec.md").exists()


def test_cli_audit_command(tmp_path: Path, capsys) -> None:
    import pytest
    from spec.cli import main
    from spec.governance.project import ProjectGovernance

    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["audit", "--root", str(tmp_path), "--json"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True


def test_verify_includes_scenario_traceability(tmp_path: Path, capsys) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Trace Feature", "Description")
    spec_md = workflow.feature_dir("trace-feature") / "spec.md"
    spec_md.write_text(
        "# Spec: Trace Feature\n\n@s1\nScenario: First\n  Given a\n  When b\n  Then c\n",
        encoding="utf-8",
    )
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_trace.py").write_text("def test_s1():\n    pass\n", encoding="utf-8")

    config = tmp_path / ".spec/verification.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "smoke",
                        "command": [sys.executable, "-c", "print('test_s1: verified PASS')"],
                    }
                ],
            }
        )
    )

    assert run_verify(tmp_path, as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "traceability" in payload
    assert payload["traceability"]["total"] == 1
    assert payload["traceability"]["covered"] == 1


def test_cli_test_assist_command(tmp_path: Path, capsys) -> None:
    import pytest
    from spec.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["test-assist", "--root", str(tmp_path), "--json"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "idle"


def test_cli_test_assist_plain_text_idle_has_no_uncovered(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["test-assist", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Feature: none" in out
    assert "Uncovered:" not in out


def test_doctor_cli_plain_text_output(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["doctor"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Status PASS" in out
    assert "Spec " in out
    assert "Root " in out


def test_doctor_cli_with_explicit_root(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["doctor", "--root", str(tmp_path), "--json"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["root"] == str(tmp_path.resolve())


def test_run_verify_plain_text_without_spec_md(tmp_path: Path, capsys) -> None:
    """No spec.md exists for the active feature: trace_info stays None."""
    workflow = Workflow(tmp_path)
    workflow.create_spec("Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    spec_md = workflow.feature_dir("feature") / "spec.md"
    spec_md.unlink()
    config = tmp_path / ".spec/verification.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [{"id": "smoke", "command": [sys.executable, "-c", "print('ok')"]}],
            }
        )
    )

    assert run_verify(tmp_path, as_json=False) == 0
    out = capsys.readouterr().out
    assert "Verification PASS" in out
    assert "Scenario Traceability" not in out
    assert "Evidence:" in out


def test_run_verify_plain_text_fully_covered_scenario(tmp_path: Path, capsys) -> None:
    """trace_info truthy but nothing uncovered: skip the missing-mapping line."""
    workflow = Workflow(tmp_path)
    workflow.create_spec("Trace Feature", "Description")
    spec_md = workflow.feature_dir("trace-feature") / "spec.md"
    spec_md.write_text(
        "# Spec: Trace Feature\n\n@s1\nScenario: First\n  Given a\n  When b\n  Then c\n",
        encoding="utf-8",
    )
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_trace.py").write_text("def test_s1():\n    pass\n", encoding="utf-8")

    config = tmp_path / ".spec/verification.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {
                        "id": "smoke",
                        "command": [sys.executable, "-c", "print('test_s1: verified PASS')"],
                    }
                ],
            }
        )
    )

    assert run_verify(tmp_path, as_json=False) == 0
    out = capsys.readouterr().out
    assert "Scenario Traceability: PASS" in out
    assert "Missing test mapping" not in out


def test_run_verify_returns_one_on_failing_check(tmp_path: Path) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Broken Feature", "Description")
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()
    config = tmp_path / ".spec/verification.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checks": [
                    {"id": "failing", "command": [sys.executable, "-c", "raise SystemExit(1)"]}
                ],
            }
        )
    )

    assert run_verify(tmp_path, as_json=True) == 1


def test_cli_audit_command_plain_text(tmp_path: Path, capsys) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit) as exc:
        main(["audit", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Project Audit: PASS" in out


def test_cli_test_assist_next_with_pending_scenario(tmp_path: Path, capsys) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Assist Feature", "Description")
    spec_md = workflow.feature_dir("assist-feature") / "spec.md"
    spec_md.write_text(
        "# Spec: Assist Feature\n\n@s1\nScenario: First\n  Given a\n  When b\n  Then c\n",
        encoding="utf-8",
    )
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()

    with pytest.raises(SystemExit) as exc:
        main(["test-assist", "--next", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "s1" in out


def test_cli_test_assist_next_without_pending_scenario(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["test-assist", "--next", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "No pending scenario." in out


def test_cli_test_assist_plain_text_with_uncovered(tmp_path: Path, capsys) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Assist Feature", "Description")
    spec_md = workflow.feature_dir("assist-feature") / "spec.md"
    spec_md.write_text(
        "# Spec: Assist Feature\n\n@s1\nScenario: First\n  Given a\n  When b\n  Then c\n",
        encoding="utf-8",
    )
    workflow.create_plan()
    workflow.create_tasks()
    workflow.begin_work()

    with pytest.raises(SystemExit) as exc:
        main(["test-assist", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Scenarios: 0/1 covered" in out
    assert "Uncovered:" in out
    assert "Instruction:" in out


def test_agent_install_interactive_tui_selection(tmp_path: Path, monkeypatch) -> None:
    """No agent name given, stdin is a tty and --yes was not passed."""
    ProjectGovernance(tmp_path).initialize()

    class FakeStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("spec.cli.sys.stdin", FakeStdin())
    monkeypatch.setattr("spec.core.tui.select_multiple", lambda *args, **kwargs: ["agents"])

    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert (tmp_path / "AGENTS.md").exists()


def test_agent_uninstall_unknown_agent_raises(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "nonexistent_ai", "--root", str(tmp_path)])
    assert exc.value.code == 2


@pytest.mark.parametrize("command", ["install", "uninstall"])
def test_agent_help_and_choices_list_every_recognized_agent(command: str, capsys) -> None:
    with pytest.raises(SystemExit):
        main(["agent", command, "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert "{" + ",".join(RECOGNIZED_AGENTS) + "}" in help_text
    assert "codex" in help_text


@pytest.mark.parametrize("command", ["install", "uninstall"])
def test_agent_all_is_not_an_agent(command: str, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["agent", command, "all", "--root", str(tmp_path)])
    assert exc.value.code == 2
    assert not (tmp_path / "AGENTS.md").exists()


def test_agent_uninstall_dry_run_nothing_owned_falls_through_loop(tmp_path: Path) -> None:
    """Dry-run uninstall with nothing installed: neither print branch fires."""
    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "aider", "--root", str(tmp_path)])
    assert exc.value.code == 0


def test_agent_uninstall_dry_run_reports_would_delete(tmp_path: Path, capsys) -> None:
    ProjectGovernance(tmp_path).initialize()
    with pytest.raises(SystemExit):
        main(["agent", "install", "agents", "--root", str(tmp_path)])

    with pytest.raises(SystemExit) as exc:
        main(["agent", "uninstall", "agents", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Would delete owned adapter for" in out
    assert (tmp_path / "AGENTS.md").exists()


def test_status_command_plain_text_idle(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["status", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "No active specification" in out


def test_status_command_plain_text_active(tmp_path: Path, capsys) -> None:
    workflow = Workflow(tmp_path)
    workflow.create_spec("Active Feature", "Description")

    with pytest.raises(SystemExit) as exc:
        main(["status", "--root", str(tmp_path)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "active-feature" in out


def test_main_fallback_raises_system_exit_two(monkeypatch) -> None:
    """An argparse namespace with an unrecognized command hits the final guard."""
    import argparse

    class FakeParser:
        def parse_args(self, argv: list[str] | None = None) -> argparse.Namespace:
            return argparse.Namespace(command="totally-unknown")

    monkeypatch.setattr("spec.cli.build_parser", lambda: FakeParser())

    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_version_comes_from_the_installed_distribution(capsys) -> None:
    from importlib.metadata import version

    import spec

    assert spec.__version__ == version("spec")
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"spec {version('spec')}"


def test_agent_install_picker_offers_every_recognized_agent(tmp_path: Path, monkeypatch) -> None:
    ProjectGovernance(tmp_path).initialize()
    offered: list[tuple[str, str]] = []

    class FakeStdin:
        def isatty(self) -> bool:
            return True

    def pick(title: str, options, default_checked=None) -> list[str]:
        offered.extend(options)
        return ["claude"]

    monkeypatch.setattr("spec.cli.sys.stdin", FakeStdin())
    monkeypatch.setattr("spec.core.tui.select_multiple", pick)

    with pytest.raises(SystemExit) as exc:
        main(["agent", "install", "--root", str(tmp_path)])
    assert exc.value.code == 0
    assert offered == list(RECOGNIZED_AGENTS.items())
    assert len(set(RECOGNIZED_AGENTS.values())) == len(RECOGNIZED_AGENTS)
    assert (tmp_path / ".claude" / "skills" / "spec-new" / "SKILL.md").exists()


def test_version_without_installed_metadata_is_explicitly_unknown(monkeypatch) -> None:
    """Imported from a source tree with no distribution metadata, spec must not crash and must
    not invent a release number that could drift from pyproject.toml."""
    import importlib
    import importlib.metadata

    import spec

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    try:
        assert importlib.reload(spec).__version__ == "0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(spec)
