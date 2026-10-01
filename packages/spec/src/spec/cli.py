from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

from spec import __version__
from spec.agents import RECOGNIZED_AGENTS
from spec.core.ownership import OwnershipError
from spec.core.paths import PathBoundary
from spec.core.result import CheckStatus
from spec.core.write import SafeWriteError
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import (
    InvalidTransitionError,
    Workflow,
    WorkflowError,
    compute_tree_fingerprint,
)
from spec.verify.engine import ConfigurationError, VerificationEngine, load_checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spec",
        description="Personal policy, specification, and verification workflow.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Describe the current Spec runtime")
    doctor.add_argument("--root", type=Path, default=None, help="Target repository root")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable output")

    init = subparsers.add_parser("init", help="Initialize repository-local governance")
    init.add_argument("--root", type=Path, default=Path.cwd())

    agent = subparsers.add_parser("agent", help="Manage reversible coding-agent adapters")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_install = agent_sub.add_parser("install", help="Install coding agent governance adapters")
    agent_install.add_argument(
        "agent",
        nargs="?",
        default=None,
        choices=RECOGNIZED_AGENTS,
        help="Agent to install (default: agents)",
    )
    agent_install.add_argument("--root", type=Path, default=Path.cwd())
    agent_install.add_argument(
        "--file",
        type=str,
        default=None,
        help="Target file for custom agent (defaults to AGENTS.md)",
    )
    agent_install.add_argument(
        "--yes", "-y", action="store_true", help="Non-interactive execution with defaults"
    )
    agent_uninstall = agent_sub.add_parser(
        "uninstall", help="Remove Spec-owned governance adapters"
    )
    agent_uninstall.add_argument(
        "agent",
        nargs="?",
        default="agents",
        choices=RECOGNIZED_AGENTS,
        help="Agent to uninstall (default: agents)",
    )
    agent_uninstall.add_argument("--root", type=Path, default=Path.cwd())
    agent_uninstall.add_argument(
        "--file",
        type=str,
        default=None,
        help="Target file for custom agent (defaults to AGENTS.md)",
    )
    agent_uninstall.add_argument(
        "--apply", action="store_true", help="Delete after ownership validation; default is dry-run"
    )

    preflight = subparsers.add_parser(
        "preflight",
        help="Agnostic pre-flight validation, baseline check, and worktree provisioning",
    )
    preflight.add_argument("name", help="Feature name")
    preflight.add_argument("--from", dest="from_branch", default=None, help="Base branch")
    preflight.add_argument("--branch", default=None, help="Target feature branch")
    preflight.add_argument(
        "--no-worktree",
        dest="worktree",
        action="store_false",
        help="Work in the current directory instead of a new Git worktree",
    )
    preflight.add_argument("--description", default="", help="Feature description")
    preflight.add_argument("--root", type=Path, default=Path.cwd())
    preflight.add_argument("--json", action="store_true")

    new = subparsers.add_parser("new", help="Create a new active specification")
    new.add_argument("name")
    new.add_argument("--description", default="")
    new.add_argument("--root", type=Path, default=Path.cwd())

    plan = subparsers.add_parser("plan", help="Create the plan for the active specification")
    plan.add_argument("--root", type=Path, default=Path.cwd())

    tasks = subparsers.add_parser("tasks", help="Create tasks for the active plan")
    tasks.add_argument("--root", type=Path, default=Path.cwd())

    work = subparsers.add_parser("work", help="Mark the active tasks ready for implementation")
    work.add_argument("--root", type=Path, default=Path.cwd())

    verify = subparsers.add_parser("verify", help="Run configured checks and record evidence")
    verify.add_argument("--root", type=Path, default=Path.cwd())
    verify.add_argument("--json", action="store_true")

    finish = subparsers.add_parser("finish", help="Complete work after a passing verification")
    finish.add_argument("--root", type=Path, default=Path.cwd())

    status = subparsers.add_parser("status", help="Show recoverable workflow state")
    status.add_argument("--root", type=Path, default=Path.cwd())
    status.add_argument("--json", action="store_true")

    audit = subparsers.add_parser(
        "audit", help="Audit repository and active spec against checkpoints"
    )
    audit.add_argument("--root", type=Path, default=Path.cwd())
    audit.add_argument("--json", action="store_true")

    assist = subparsers.add_parser("test-assist", help="Assistance for agents executing TDD tests")
    assist.add_argument(
        "--next", action="store_true", help="Output only the next uncovered scenario"
    )
    assist.add_argument("--root", type=Path, default=Path.cwd())
    assist.add_argument("--json", action="store_true")
    return parser


def run_doctor(root: str | Path | None = None, *, as_json: bool = False) -> int:
    resolved_root = str(Path(root).resolve()) if root is not None else str(Path.cwd().resolve())
    payload = {
        "status": "PASS",
        "spec_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.system().lower(),
        "root": resolved_root,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Spec {payload['spec_version']}")
        print(f"Python {payload['python_version']}")
        print(f"Platform {payload['platform']}")
        print(f"Root {payload['root']}")
        print("Status PASS")
    return 0


def run_verify(root: str | Path, *, as_json: bool = False) -> int:
    workflow = Workflow(root)
    workflow.validate_can_verify()

    fingerprint_before = compute_tree_fingerprint(root)
    checks = load_checks(root)
    report = VerificationEngine(root).run(checks)
    fingerprint_after = compute_tree_fingerprint(root)

    if fingerprint_before != fingerprint_after:
        raise InvalidTransitionError(
            "Verification rejected: Working tree was modified during verification checks (fingerprint mismatch)"
        )

    current_snapshot = workflow.status()
    assert current_snapshot is not None
    boundary = PathBoundary(root)
    feature_dir = boundary.resolve(f".spec/specs/{current_snapshot.feature}")
    spec_path = feature_dir / "spec.md"
    trace_info: dict[str, Any] | None = None
    if spec_path.is_file():
        from spec.spec.trace import extract_scenarios, find_test_mappings

        scenarios = extract_scenarios(spec_path.read_text(encoding="utf-8"))
        if scenarios:
            trace_report = find_test_mappings(
                scenarios,
                boundary.root,
                feature_dir=feature_dir,
                check_results=report.checks,
            )
            trace_info = {
                "total": trace_report.total,
                "covered": trace_report.covered_count,
                "coverage_percent": trace_report.coverage_percent,
                "uncovered": trace_report.uncovered,
            }

    # Determine overall status including traceability BEFORE recording
    has_trace_gap = bool(trace_info and trace_info["uncovered"])
    if has_trace_gap and report.status is CheckStatus.PASS:
        overall_status = CheckStatus.INCOMPLETE
    else:
        overall_status = report.status

    snapshot, evidence_path = workflow.record_verification(
        report,
        tree_fingerprint=fingerprint_after,
        verification_status=overall_status,
        trace_info=trace_info,
    )
    payload = report.to_dict()
    payload["feature"] = snapshot.feature
    payload["evidence_path"] = str(evidence_path)
    payload["status"] = overall_status.value
    payload["passed"] = overall_status is CheckStatus.PASS
    if trace_info:
        payload["traceability"] = trace_info

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Verification {overall_status.value}")
        for check in report.checks:
            requirement = "required" if check.required else "optional"
            print(f"- {check.id}: {check.status.value} ({requirement}) — {check.summary}")
        if trace_info:
            status_tag = "PASS" if not trace_info["uncovered"] else "INCOMPLETE"
            print(
                f"Scenario Traceability: {status_tag} ({trace_info['covered']}/{trace_info['total']} covered, {trace_info['coverage_percent']:.0f}%)"
            )
            if trace_info["uncovered"]:
                print(f"  Missing test mapping for: {', '.join(trace_info['uncovered'])}")
        print(f"Evidence: {evidence_path}")

    if overall_status is CheckStatus.PASS:
        return 0
    if overall_status is CheckStatus.FAIL:
        return 1
    return 2


def run_audit(root: str | Path, *, as_json: bool = False) -> int:
    from spec.governance.audit import ProjectAuditor

    report = ProjectAuditor(root).audit()
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status_str = "PASS" if report.passed else "FAIL"
        print(f"Project Audit: {status_str}")
        for item in report.items:
            mark = "[x]" if item.passed else "[ ]"
            print(f"- {mark} {item.id}: {item.description} ({item.details})")
    return 0 if report.passed else 1


def run_test_assist(root: str | Path, *, next_only: bool = False, as_json: bool = False) -> int:
    from spec.spec.assist import TestAssistant

    ctx = TestAssistant(root).inspect()
    if as_json:
        print(json.dumps(ctx.to_dict(), indent=2))
    elif next_only:
        if ctx.next_scenario:
            print(f"{ctx.next_scenario.tag}: {ctx.next_scenario.title}")
        else:
            print("No pending scenario.")
    else:
        print(f"Feature: {ctx.feature} (stage={ctx.stage})")
        print(f"Scenarios: {ctx.covered_count}/{ctx.total_scenarios} covered")
        if ctx.uncovered:
            print(f"Uncovered: {', '.join(ctx.uncovered)}")
        print(f"Instruction: {ctx.actionable_instruction}")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            if getattr(args, "root", None) is not None:
                raise SystemExit(run_doctor(root=args.root, as_json=args.json))
            raise SystemExit(run_doctor(as_json=args.json))
        if args.command == "init":
            result = ProjectGovernance(args.root).initialize()
            print(
                f"Governance initialized ({len(result.created)} created, {len(result.existing)} existing)"
            )
            raise SystemExit(0)
        if args.command == "agent" and args.agent_command == "install":
            from spec.agents import AgentsAdapter, ClaudeAdapter

            if args.agent:
                keys_to_install = [args.agent]
            else:
                if sys.stdin.isatty() and not args.yes:
                    from spec.core.tui import select_multiple

                    options = [("agents", "Universal AGENTS.md Standard (AGENTS.md)")]
                    keys_to_install = select_multiple(
                        "Select AI coding agents to configure with Spec governance:",
                        options,
                        default_checked=["agents"],
                    )
                else:
                    keys_to_install = ["agents"]

            for k in keys_to_install:
                label = RECOGNIZED_AGENTS[k]
                adapter_cls = ClaudeAdapter if k == "claude" else AgentsAdapter
                adapter_instance = (
                    adapter_cls(args.root, target=args.file, agent=k)
                    if args.file
                    else adapter_cls(args.root, agent=k)
                )
                res = adapter_instance.install()
                print(f"Configured {label}: {res.path}")
            raise SystemExit(0)
        if args.command == "agent" and args.agent_command == "uninstall":
            from spec.agents import AgentsAdapter, ClaudeAdapter

            label = RECOGNIZED_AGENTS[args.agent]
            adapter_cls = ClaudeAdapter if args.agent == "claude" else AgentsAdapter
            adapter_instance = (
                adapter_cls(args.root, target=args.file, agent=args.agent)
                if args.file
                else adapter_cls(args.root, agent=args.agent)
            )
            del_res = adapter_instance.uninstall(dry_run=not args.apply)
            if not args.apply and del_res.would_delete:
                print(f"Would delete owned adapter for {label}: {del_res.path}")
            elif args.apply:
                print(f"Cleaned adapter for {label}")
            raise SystemExit(0)
        if args.command == "preflight":
            from spec.core.preflight import PreflightManager

            mgr = PreflightManager(args.root)
            preflight_res = mgr.run(
                args.name,
                base_branch=args.from_branch,
                branch=args.branch,
                use_worktree=args.worktree,
                description=args.description,
            )
            if args.json:
                print(json.dumps(preflight_res, indent=2))
            else:
                if preflight_res["status"] == "FAIL":
                    print(f"Preflight FAIL: {preflight_res['error']}")
                    if preflight_res.get("evidence_path"):
                        print(f"Evidence: {preflight_res['evidence_path']}")
                else:
                    print(f"Preflight READY: feature '{preflight_res['feature']}' initialized")
                    print(f"Worktree: {preflight_res['worktree_path']}")
                    print(
                        f"Branch: {preflight_res['branch']} (from {preflight_res['base_branch']})"
                    )
                    print(f"Baseline: {preflight_res['baseline']}")
            raise SystemExit(0 if preflight_res["status"] == "READY" else 1)
        if args.command == "new":
            snapshot = Workflow(args.root).create_spec(args.name, args.description)
            print(f"Created spec {snapshot.feature} (stage={snapshot.stage.value})")
            raise SystemExit(0)
        if args.command == "plan":
            snapshot = Workflow(args.root).create_plan()
            print(f"Created plan for {snapshot.feature} (stage={snapshot.stage.value})")
            raise SystemExit(0)
        if args.command == "tasks":
            snapshot = Workflow(args.root).create_tasks()
            print(f"Created tasks for {snapshot.feature} (stage={snapshot.stage.value})")
            raise SystemExit(0)
        if args.command == "work":
            snapshot = Workflow(args.root).begin_work()
            print(f"Started work for {snapshot.feature} (stage={snapshot.stage.value})")
            raise SystemExit(0)
        if args.command == "verify":
            raise SystemExit(run_verify(args.root, as_json=args.json))
        if args.command == "finish":
            snapshot = Workflow(args.root).finish()
            print(f"Completed {snapshot.feature} (stage={snapshot.stage.value})")
            raise SystemExit(0)
        if args.command == "status":
            current_status = Workflow(args.root).status()
            payload = (
                {"status": "IDLE", "active_feature": None, "stage": None}
                if current_status is None
                else {
                    "status": "ACTIVE",
                    "active_feature": current_status.feature,
                    "stage": current_status.stage.value,
                    "updated_at": current_status.updated_at,
                    "verification_status": (
                        current_status.verification_status.value
                        if current_status.verification_status
                        else None
                    ),
                    "evidence_path": current_status.evidence_path,
                }
            )
            if args.json:
                print(json.dumps(payload, indent=2))
            elif current_status is None:
                print("No active specification")
            else:
                print(f"{current_status.feature}: {current_status.stage.value}")
            raise SystemExit(0)
        if args.command == "audit":
            raise SystemExit(run_audit(args.root, as_json=args.json))
        if args.command == "test-assist":
            raise SystemExit(run_test_assist(args.root, next_only=args.next, as_json=args.json))
    except (WorkflowError, ConfigurationError, OwnershipError, SafeWriteError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
