from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from spec import __version__
from spec.adapters.codex import CodexAdapter
from spec.core.ownership import OwnershipError
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

    spec = subparsers.add_parser("spec", help="Create and inspect specification work")
    spec_sub = spec.add_subparsers(dest="spec_command")
    spec_new = spec_sub.add_parser("new", help="Create a new active specification")
    spec_new.add_argument("name")
    spec_new.add_argument("--description", default="")
    spec_new.add_argument("--root", type=Path, default=Path.cwd())

    new = subparsers.add_parser("new", help="Create a new active specification (alias for spec new)")
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
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Verification {report.status.value}")
        for check in report.checks:
            requirement = "required" if check.required else "optional"
            print(f"- {check.id}: {check.status.value} ({requirement}) — {check.summary}")
        print(f"Evidence: {evidence_path}")
    if report.status is CheckStatus.PASS:
        return 0
    if report.status is CheckStatus.FAIL:
        return 1
    return 2


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            raise SystemExit(run_doctor(as_json=args.json))
        if args.command == "init":
            result = ProjectGovernance(args.root).initialize()
            print(f"Governance initialized ({len(result.created)} created, {len(result.existing)} existing)")
            raise SystemExit(0)
        if args.command == "agent" and args.agent_command == "install":
            result = CodexAdapter(args.root).install()
            action = "created" if result.created else "updated"
            print(f"Codex adapter {action}: {result.path}")
            raise SystemExit(0)
        if args.command == "agent" and args.agent_command == "uninstall":
            result = CodexAdapter(args.root).uninstall(dry_run=not args.apply)
            if result.would_delete:
                print(f"Would delete owned adapter: {result.path}")
            else:
                print(f"Deleted owned adapter: {result.path}")
            raise SystemExit(0)
        if (args.command == "spec" and getattr(args, "spec_command", None) == "new") or args.command == "new":
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
                        snapshot.verification_status.value
                        if snapshot.verification_status
                        else None
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
    except (WorkflowError, ConfigurationError, OwnershipError, SafeWriteError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
