from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from spec import __version__
from spec.core.ownership import OwnershipError
from spec.core.paths import PathBoundary
from spec.core.result import CheckStatus
from spec.core.write import SafeWriteError
from spec.governance.project import ProjectGovernance
from spec.spec.workflow import Workflow, WorkflowError
from spec.verify.engine import ConfigurationError, VerificationEngine, load_checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spec",
        description="Personal policy, specification, and verification workflow.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Describe the current Spec runtime")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable output")

    init = subparsers.add_parser("init", help="Initialize repository-local governance")
    init.add_argument("--root", type=Path, default=Path.cwd())

    agent = subparsers.add_parser("agent", help="Manage reversible coding-agent adapters")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_install = agent_sub.add_parser("install", help="Install the Codex AGENTS.md adapter")
    agent_install.add_argument("--root", type=Path, default=Path.cwd())
    agent_uninstall = agent_sub.add_parser("uninstall", help="Remove Spec-owned AGENTS.md")
    agent_uninstall.add_argument("--root", type=Path, default=Path.cwd())
    agent_uninstall.add_argument(
        "--apply", action="store_true", help="Delete after ownership validation; default is dry-run"
    )

    preflight = subparsers.add_parser(
        "preflight", help="Agnostic pre-flight validation, baseline check, and worktree provisioning"
    )
    preflight.add_argument("name", help="Feature name")
    preflight.add_argument("--from", dest="from_branch", default=None, help="Base branch")
    preflight.add_argument("--branch", default=None, help="Target feature branch")
    preflight.add_argument("--worktree", action="store_true", default=True, help="Provision isolated Git Worktree")
    preflight.add_argument("--no-worktree", dest="worktree", action="store_false", help="Do not provision worktree")
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

    mutate = subparsers.add_parser("mutate", help="Run zero-dependency mutation testing on a file")
    mutate.add_argument("target", type=Path, help="Target Python file to mutate")
    mutate.add_argument("--test-cmd", type=str, help="Test command to run (e.g. 'pytest -q')")
    mutate.add_argument("--max", type=int, default=100, help="Maximum mutants to evaluate")
    mutate.add_argument("--threshold", type=float, default=100.0, help="Required killed score percentage")
    mutate.add_argument("--root", type=Path, default=Path.cwd())
    mutate.add_argument("--json", action="store_true")

    audit = subparsers.add_parser("audit", help="Audit repository and active spec against checkpoints")
    audit.add_argument("--root", type=Path, default=Path.cwd())
    audit.add_argument("--json", action="store_true")

    assist = subparsers.add_parser("test-assist", help="Assistance for agents executing TDD tests")
    assist.add_argument("--next", action="store_true", help="Output only the next uncovered scenario")
    assist.add_argument("--root", type=Path, default=Path.cwd())
    assist.add_argument("--json", action="store_true")

    judge = subparsers.add_parser("judge", help="Prepare craftsmanship evaluation context or record verdict")
    judge.add_argument("--approve", action="store_true", help="Record an APPROVED verdict")
    judge.add_argument("--reject", action="store_true", help="Record a CHANGES_REQUESTED verdict")
    judge.add_argument("--remarks", default="", help="Remarks or reasons for the verdict")
    judge.add_argument("--root", type=Path, default=Path.cwd())
    judge.add_argument("--json", action="store_true")
    return parser


def run_doctor(*, as_json: bool = False) -> int:
    payload = {
        "status": "PASS",
        "spec_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.system().lower(),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Spec {payload['spec_version']}")
        print(f"Python {payload['python_version']}")
        print(f"Platform {payload['platform']}")
        print("Status PASS")
    return 0


def run_verify(root: str | Path, *, as_json: bool = False) -> int:
    checks = load_checks(root)
    report = VerificationEngine(root).run(checks)
    snapshot, evidence_path = Workflow(root).record_verification(report)
    payload = report.to_dict()
    payload["feature"] = snapshot.feature
    payload["evidence_path"] = str(evidence_path)

    # Check scenario traceability if spec.md defines scenarios
    boundary = PathBoundary(root)
    feature_dir = boundary.resolve(f".spec/specs/{snapshot.feature}")
    spec_path = feature_dir / "spec.md"
    trace_info = None
    if spec_path.is_file():
        from spec.spec.trace import extract_scenarios, find_test_mappings

        scenarios = extract_scenarios(spec_path.read_text(encoding="utf-8"))
        if scenarios:
            trace_report = find_test_mappings(scenarios, boundary.root, feature_dir=feature_dir)
            trace_info = {
                "total": trace_report.total,
                "covered": trace_report.covered_count,
                "coverage_percent": trace_report.coverage_percent,
                "uncovered": trace_report.uncovered,
            }
            payload["traceability"] = trace_info

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Verification {report.status.value}")
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
    if report.status is CheckStatus.PASS:
        return 0
    if report.status is CheckStatus.FAIL:
        return 1
    return 2


def run_mutate(
    target: Path,
    *,
    test_cmd: str | list[str] | None = None,
    root: Path | None = None,
    max_mutants: int = 100,
    threshold: float = 100.0,
    as_json: bool = False,
) -> int:
    import shlex

    from spec.verify.mutate import run_mutation_analysis

    parsed_cmd = shlex.split(test_cmd) if isinstance(test_cmd, str) else test_cmd
    res = run_mutation_analysis(
        target,
        test_cmd=parsed_cmd,
        cwd=root,
        max_mutants=max_mutants,
        verbose=not as_json,
    )
    passed = res.passed and res.score >= threshold
    payload = {
        "target": res.target_path,
        "total": res.total,
        "killed": res.killed,
        "survived": res.survived,
        "score": res.score,
        "passed": passed,
        "survivors": [s.describe(target) for s in res.survivors],
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        status_str = "PASS" if passed else "FAIL"
        print(f"\nMutation {status_str}: {res.score:.1f}% killed (threshold: {threshold:.1f}%)")
        print(f"Total: {res.total} | Killed: {res.killed} | Survived: {res.survived}")
        if res.survivors:
            print("Surviving mutants (holes in test suite):")
            for s in res.survivors:
                print(f"  - {s.describe(target)}")
    return 0 if passed else 1


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


def run_judge(
    root: str | Path,
    *,
    approve: bool = False,
    reject: bool = False,
    remarks: str = "",
    as_json: bool = False,
) -> int:
    from spec.governance.judge import SpecJudge

    judge = SpecJudge(root)
    if approve or reject:
        verdict = "APPROVED" if approve else "CHANGES_REQUESTED"
        verdict_path = judge.record_verdict(verdict, remarks)
        if as_json:
            print(
                json.dumps(
                    {"status": "RECORDED", "verdict": verdict, "path": str(verdict_path)},
                    indent=2,
                )
            )
        else:
            print(f"Recorded Judge verdict: {verdict} -> {verdict_path}")
        return 0

    ctx = judge.evaluate_context()
    if as_json:
        print(json.dumps(ctx.to_dict(), indent=2))
    else:
        print(ctx.prompt_for_llm)
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            raise SystemExit(run_doctor(as_json=args.json))
        if args.command == "init":
            result = ProjectGovernance(args.root).initialize()
            print(
                f"Governance initialized ({len(result.created)} created, {len(result.existing)} existing)"
            )
            raise SystemExit(0)
        if args.command == "agent" and args.agent_command == "install":
            from spec.adapters import SPEC_ADAPTERS
            from spec.core.tui import select_multiple

            options = [(k, label) for k, (label, _) in SPEC_ADAPTERS.items()]
            selected_keys = select_multiple(
                "Select AI coding agents to configure with Spec governance:",
                options,
                default_checked=[k for k, _ in options],
            )
            for k in selected_keys:
                label, cls = SPEC_ADAPTERS[k]
                res = cls(args.root).install()
                print(f"Configured {label}: {res.path}")
            raise SystemExit(0)
        if args.command == "agent" and args.agent_command == "uninstall":
            from spec.adapters import SPEC_ADAPTERS

            for label, cls in SPEC_ADAPTERS.values():
                res = cls(args.root).uninstall(dry_run=not args.apply)
                if not args.apply and res.would_delete:
                    print(f"Would delete owned adapter for {label}: {res.path}")
                elif args.apply:
                    print(f"Cleaned adapter for {label}")
            raise SystemExit(0)
        if args.command == "preflight":
            from spec.core.preflight import PreflightManager

            mgr = PreflightManager(args.root)
            res = mgr.run(
                args.name,
                base_branch=args.from_branch,
                branch=args.branch,
                use_worktree=args.worktree,
                description=args.description,
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                if res["status"] == "FAIL":
                    print(f"Preflight FAIL: {res['error']}")
                    if res.get("evidence_path"):
                        print(f"Evidence: {res['evidence_path']}")
                else:
                    print(f"Preflight READY: feature '{res['feature']}' initialized")
                    print(f"Worktree: {res['worktree_path']}")
                    print(f"Branch: {res['branch']} (from {res['base_branch']})")
                    print(f"Baseline: {res['baseline']}")
            raise SystemExit(0 if res["status"] == "READY" else 1)
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
            snapshot = Workflow(args.root).status()
            payload = (
                {"status": "IDLE", "active_feature": None, "stage": None}
                if snapshot is None
                else {
                    "status": "ACTIVE",
                    "active_feature": snapshot.feature,
                    "stage": snapshot.stage.value,
                    "updated_at": snapshot.updated_at,
                    "verification_status": (
                        snapshot.verification_status.value if snapshot.verification_status else None
                    ),
                    "evidence_path": snapshot.evidence_path,
                }
            )
            if args.json:
                print(json.dumps(payload, indent=2))
            elif snapshot is None:
                print("No active specification")
            else:
                print(f"{snapshot.feature}: {snapshot.stage.value}")
            raise SystemExit(0)
        if args.command == "mutate":
            raise SystemExit(
                run_mutate(
                    args.target,
                    test_cmd=args.test_cmd,
                    root=args.root,
                    max_mutants=args.max,
                    threshold=args.threshold,
                    as_json=args.json,
                )
            )
        if args.command == "audit":
            raise SystemExit(run_audit(args.root, as_json=args.json))
        if args.command == "test-assist":
            raise SystemExit(run_test_assist(args.root, next_only=args.next, as_json=args.json))
        if args.command == "judge":
            raise SystemExit(
                run_judge(
                    args.root,
                    approve=args.approve,
                    reject=args.reject,
                    remarks=args.remarks,
                    as_json=args.json,
                )
            )
    except (WorkflowError, ConfigurationError, OwnershipError, SafeWriteError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
