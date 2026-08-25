import argparse
import json
import sys
from pathlib import Path

from sdd_engine.core import memory, parser, exceptions
from sdd_engine.core.exceptions import SDDError
from sdd_engine.lifecycle import feature, constitution, finish
from sdd_engine.harness import analyzer, harness, hooks, quality_gate, runner, verify
from sdd_engine.adapters import bridge, global_skills, reset, revoke, sync





import argparse
import json
import sys
from pathlib import Path

from sdd_engine.core import memory, parser, exceptions
from sdd_engine.core.exceptions import SDDError
from sdd_engine.lifecycle import feature, constitution, finish
from sdd_engine.harness import analyzer, harness, hooks, quality_gate, runner, verify
from sdd_engine.adapters import bridge, global_skills, reset, revoke, sync


class CustomArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser providing clean error formatting and helpful usage prompts."""

    def error(self, message: str):
        sys.stderr.write(f"\n❌ Argument Error: {message}\n\n")
        self.print_help(sys.stderr)
        sys.exit(2)


def main():
    try:
        _run_cli()
    except (SDDError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _run_cli():
    argp = CustomArgumentParser(
        description="""Cucco SpecOps Engine — Spec-Driven Development (SDD) AI Governance & CLI Orchestrator

Strict 8-Phase Lifecycle:
  1. sdd specify   ➜ Phase 1: Functional specification (spec.md)
  2. sdd clarify   ➜ Phase 2: Ambiguity resolution and risk audit (clarify.md)
  3. sdd plan      ➜ Phase 3: Technical blueprint and contracts (plan.md)
  4. sdd checklist ➜ Phase 4: Quality Gates and Definition of Done (checklist.md)
  5. sdd tasks     ➜ Phase 5: Atomic executable task breakdown (tasks.md)
  6. sdd analyze   ➜ Phase 6: Static cross-artifact consistency & AST contract audit
  7. sdd exec      ➜ Phase 7: Iterative multi-agent execution (Worker + QA Reviewer)
  8. sdd converge  ➜ Phase 8: Final convergence verification and Gherkin check

* For fast-path bug fixes and minor patches, use: `sdd quick`
* To configure AI adapters (Claude, Cursor, Antigravity, Copilot, etc.), use: `sdd adapter` or `sdd bridge`
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = argp.add_subparsers(dest="command", help="Available SDD commands")

    # Harness
    ph = sub.add_parser("harness", help="Multi-agent SDD execution harness orchestrator")
    ph.add_argument("subcmd", choices=["run", "status", "next", "log-worker", "log-qa"])
    ph.add_argument("--feature", help="Target feature name")
    ph.add_argument("--max-retries", type=int, default=3, help="Maximum automatic retry limit")
    ph.add_argument("--task-id", help="Task ID for logging")
    ph.add_argument("--summary", help="Summary for role logging")
    ph.add_argument("--details", default="", help="Detailed text or diff")
    ph.add_argument("--passed", action="store_true", help="QA approval flag")

    # Init
    pi = sub.add_parser("init", help="Initialize SDD workspace in project with Constitution")
    pi.add_argument("dir", nargs="?", default=".", help="Target project directory")
    pi.add_argument("--interactive", "-i", action="store_true", help="Interactively select AI assistants")
    pi.add_argument("--all", action="store_true", help="Configure adapters for all AI agents")
    pi.add_argument("--restore-backup", action="store_true", help="Restore specifications and history from previous backup .specify-backup-*")
    pi.add_argument("--claude", action="store_true")
    pi.add_argument("--copilot", action="store_true")
    pi.add_argument("--cursor", action="store_true")
    pi.add_argument("--gemini", action="store_true")
    pi.add_argument("--agy", action="store_true")
    pi.add_argument("--chatgpt", action="store_true")
    pi.add_argument("--windsurf", action="store_true")

    # Feature
    pf = sub.add_parser("feature", help="Set, list, or inspect active repository features")
    pf.add_argument("subcmd", nargs="?", help="Subcommand for feature management or feature name to activate")
    pf.add_argument("--from-branch", "-b", help="Base branch from which to branch the new worktree (e.g. main, develop)")
    pf.add_argument("args", nargs="*", help="Subcommand arguments")

    # Lifecycle Phases
    phase_help = {
        "specify": "Phase 1: Defines functional specification (spec.md) with requirements, stories, and Gherkin",
        "clarify": "Phase 2: Audits and resolves ambiguities, assumptions, and edge cases in spec.md (clarify.md)",
        "plan": "Phase 3: Designs technical blueprint, data contracts (Zod/DTOs), and Mermaid diagrams (plan.md)",
        "checklist": "Phase 4: Establishes Quality Gates, Definition of Done, and required test assertions (checklist.md)",
        "tasks": "Phase 5: Atomizes technical plan into executable tasks ordered across 4 pillars (tasks.md)",
        "analyze": "Phase 6: Performs static cross-artifact consistency audit and AST contract validation",
        "exec": "Phase 7: Initiates iterative multi-agent task execution with Worker and QA Reviewer",
        "converge": "Phase 8: Validates final convergence, running test suite, checklist, and Gherkin criteria",
        "quick": "Fast-path workflow for bug fixes, minor patches, or hotfixes (spec-quick.md)",
    }

    for cmd, htext in phase_help.items():
        sp = sub.add_parser(cmd, help=htext)
        sp.add_argument("--from-branch", "-b", help="Base branch for new worktree (e.g. main, develop)")
        sp.add_argument("args", nargs="*", help="Optional phase arguments (e.g. feature name)")

    # Utils
    pa = sub.add_parser("audit", help="Audits codebase compliance and technical debt")
    pa.add_argument("args", nargs="*")

    pr = sub.add_parser("reset", help="Global reset of environment and worktrees")
    pr.add_argument("--force", "-f", action="store_true")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--target", default="all", choices=["all", "cache", "worktrees", "repos"])

    # Bridge / Adapter
    for bcmd in ["bridge", "adapter"]:
        pb = sub.add_parser(bcmd, help="Generates and configures native Multi-AI adapters (Antigravity, Claude, Copilot, Cursor, etc.)")
        pb.add_argument("--interactive", "-i", action="store_true", help="Interactively select AI assistants")
        pb.add_argument("--all", action="store_true", help="Configure adapters for all AI agents")
        pb.add_argument("--claude", action="store_true")
        pb.add_argument("--copilot", action="store_true")
        pb.add_argument("--cursor", action="store_true")
        pb.add_argument("--gemini", action="store_true")
        pb.add_argument("--agy", action="store_true")
        pb.add_argument("--chatgpt", action="store_true")
        pb.add_argument("--windsurf", action="store_true")
        pb.add_argument("--target-dir", "-o", default=".")

    # Remove / Revoke
    for rcmd in ["remove", "revoke"]:
        prv = sub.add_parser(rcmd, help="Revokes and removes SDD and AI configurations from project with automatic backup")
        prv.add_argument("dir", nargs="?", default=".", help="Project directory")
        prv.add_argument("--force", "-f", action="store_true", help="Force removal without interactive confirmation")
        prv.add_argument("--no-backup", action="store_true", help="Skip creating backup directory .specify-backup-*")

    # Finish / PR
    pfsh = sub.add_parser("finish", help="Finalizes SDD cycle: push, PR with gh CLI, worktree cleanup, and pull to main")
    pfsh.add_argument("--no-pr", action="store_true", help="Skip GitHub PR creation")
    pfsh.add_argument("--title", help="Pull Request title")

    # Global Skills Setup
    psg = sub.add_parser("setup-global", help="Installs global SDD skills for AI assistants (~/.gemini/config/skills, ~/.agents/skills)")
    psg.add_argument("--force", "-f", action="store_true", default=True, help="Overwrite existing global skills")

    # Memory
    pm = sub.add_parser("memory", help="Project memory tools")
    pm.add_argument("subcmd", choices=["init", "log", "read", "consolidate"])
    pm.add_argument("args", nargs="*")

    # Parser
    pp = sub.add_parser("parse", help="Parses functional specification")
    pp.add_argument("input")
    pp.add_argument("-o", "--output")

    # Runner
    prn = sub.add_parser("run", help="Executes isolated command in Git Worktree")
    prn.add_argument("--repo")
    prn.add_argument("--branch")
    prn.add_argument("--cleanup", action="store_true")
    prn.add_argument("cmd", nargs=argparse.REMAINDER)

    # Verify
    pv = sub.add_parser("verify", help="Executes automated SDD verification quality gate")
    pv.add_argument("--dir", default=".", help="Target directory to verify")
    pv.add_argument("--json", action="store_true", help="Output in JSON format")

    # Hook
    phk = sub.add_parser("hook", help="Executes security and post-tool verification hooks")
    phk.add_argument("event", choices=["pre-tool", "post-tool"], help="Hook event type")
    phk.add_argument("--tool-name", default="", help="Executed tool name")
    phk.add_argument("--tool-args", default=None, help="Tool arguments")
    phk.add_argument("--dir", default=".", help="Target directory")

    # Quality Gate
    pg = sub.add_parser("gate", help="Quality Gate: Baseline capture and regression detection")
    pg.add_argument("subcmd", choices=["snapshot", "check"], help="Gate subcommand")
    pg.add_argument("--output", "-o", help="JSON path to save baseline snapshot")
    pg.add_argument("--baseline", "-b", help="JSON path of baseline for check")
    pg.add_argument("--phase", default="pre-task", choices=["pre-task", "post-task", "convergence"], help="Gate check phase")
    pg.add_argument("--json", action="store_true", help="Output in JSON format")

    # MCP Server
    pmcp = sub.add_parser("mcp", help="Launches native Model Context Protocol (MCP) server over stdio")
    pmcp.add_argument("dir", nargs="?", default=".", help="Project root directory")

    # Match Rules (Dynamic Context Budgeting)
    pmr = sub.add_parser("match-rules", help="Dynamically filters applicable rules to optimize token budgets")
    pmr.add_argument("files", nargs="*", help="Modified files or paths of interest")
    pmr.add_argument("--files", "-f", dest="files_flag", nargs="*", help="Optional flag for modified files")
    pmr.add_argument("--dir", default=".", help="Project directory")
    pmr.add_argument("--json", action="store_true", help="Output in JSON format")
    pmr.add_argument("--render", action="store_true", help="Render full Markdown context")

    # Sync
    psy = sub.add_parser("sync", help="Synchronizes global CLI installation and updates project AI adapters")
    psy.add_argument("dir", nargs="?", default=".", help="Target directory")
    psy.add_argument("--quiet", "-q", action="store_true", help="Suppress detailed output")

    args = argp.parse_args()

    if not args.command:
        argp.print_help()
        sys.exit(0)

    if args.command == "harness":
        sess = harness.HarnessSession(feature_name=args.feature, max_retries=args.max_retries)
        if args.subcmd in ["status", "run"]:
            st = sess.status()
            print("==> SDD Execution Harness Status")
            print(f"    Feature:    {st['feature']}")
            print(f"    Tasks File: {st['tasks_file']}")
            print(f"    Total:      {st['total_tasks']} | Completed: {st['completed_tasks']} | Pending: {st['pending_tasks']}")
            if st['next_task']:
                print(f"    Next Task:  [{st['next_task'].id}] {st['next_task'].description}")
            else:
                print("    Next Task:  None (All tasks completed)")
        elif args.subcmd == "next":
            res = sess.run_next()
            print(f"==> Harness Action: {res['status']}")
            if res.get("task"):
                print(f"    Task ID: {res['task'].id}")
                print(f"    Desc:    {res['task'].description}")
        elif args.subcmd == "log-worker":
            if not args.task_id or not args.summary:
                print("Error: --task-id and --summary are required for log-worker", file=sys.stderr)
                sys.exit(1)
            path = sess.record_worker_result(args.task_id, args.summary, args.details)
            print(f"Worker log recorded: {path}")
        elif args.subcmd == "log-qa":
            if not args.task_id or not args.summary:
                print("Error: --task-id and --summary are required for log-qa", file=sys.stderr)
                sys.exit(1)
            path = sess.record_qa_result(args.task_id, args.summary, args.details, args.passed)
            print(f"QA log recorded ({'PASS' if args.passed else 'FAIL'}): {path}")

    elif args.command == "init":
        latest_b = revoke.find_latest_backup(args.dir)
        if latest_b:
            do_restore = args.restore_backup
            if not do_restore and sys.stdin and sys.stdin.isatty() and not args.all:
                try:
                    ans = input(f"📦 Detected previous backup ('{latest_b.name}').\nDo you want to restore previous specifications and history? [y/N]: ").strip().lower()
                    if ans == "y":
                        do_restore = True
                except (EOFError, KeyboardInterrupt):
                    pass

            if do_restore:
                restored = revoke.restore_backup_specs(latest_b, target_dir=args.dir)
                if restored:
                    print(f"✅ Specifications and history successfully restored from {latest_b.name}")

        memory.init(args.dir)

        # Project Constitution (Spec-Kit Aligned)
        cfile = constitution.get_constitution_file(args.dir)
        if args.interactive or (sys.stdin and sys.stdin.isatty() and not cfile.exists()):
            constitution.prompt_create_constitution(target_dir=args.dir)
        elif not cfile.exists():
            constitution.write_constitution(target_dir=args.dir)

        try:
            import sdd_engine.sdd_tui
        except ImportError:
            pass

        bridge.generate_adapters(
            target_dir=args.dir,
            gen_all=args.all,
            claude=args.claude,
            copilot=args.copilot,
            cursor=args.cursor,
            gemini=args.gemini,
            agy=args.agy,
            chatgpt=args.chatgpt,
            windsurf=args.windsurf,
            interactive=args.interactive,
        )
        global_skills.install_global_skills()

        # Propagate SDD initialization to all active worktrees
        active_wts = sync.get_active_repo_worktrees(args.dir)
        if active_wts:
            print(f"🔄 Detected {len(active_wts)} active worktree(s) in repository. Synchronizing SDD...")
            for wt in active_wts:
                memory.init(wt)
                constitution.write_constitution(target_dir=wt)
                bridge.generate_adapters(
                    target_dir=wt,
                    gen_all=args.all,
                    claude=args.claude,
                    copilot=args.copilot,
                    cursor=args.cursor,
                    gemini=args.gemini,
                    agy=args.agy,
                    chatgpt=args.chatgpt,
                    windsurf=args.windsurf,
                    interactive=False,
                )
                print(f"  ✅ SDD and AI adapters initialized in worktree: {wt.name}")

    elif args.command in ["remove", "revoke"]:
        success, bpath, removed = revoke.revoke_sdd_configuration(
            target_dir=args.dir,
            create_backup=not args.no_backup,
            force=args.force,
        )
        if success:
            if bpath:
                print(f"📦 Automatic backup created at: {bpath.name}")
            print(f"✅ Successfully removed {len(removed)} SDD and AI configuration items in {args.dir}")

    elif args.command == "setup-global":
        global_skills.install_global_skills(force=args.force)

    elif args.command == "feature":
        if not args.subcmd:
            feature.list_features()
            sys.exit(0)
        from_b = getattr(args, "from_branch", None)
        if args.subcmd == "set":
            fname = args.args[0] if args.args else ""
            feature.set_feature(fname, from_branch=from_b)
        elif args.subcmd == "get":
            feature.get_feature()
        elif args.subcmd == "phase":
            feature.update_phase(args.args[0] if args.args else "")
        elif args.subcmd == "status":
            feature.status()
        elif args.subcmd == "reset":
            feature.reset()
        elif args.subcmd in ["list", "ls"]:
            feature.list_features()
        else:
            feature.set_feature(args.subcmd, from_branch=from_b)

    elif args.command == "analyze" or args.command == "audit":
        analyzer.analyze(args.args[0] if args.args else None)
        if args.command == "analyze": feature.update_phase("analyze")

    elif args.command in ["specify", "clarify", "plan", "checklist", "tasks", "exec", "converge"]:
        if args.command == "specify" and args.args:
            from_b = getattr(args, "from_branch", None)
            feature.set_feature(args.args[0], from_branch=from_b)
        else:
            active = feature.get_active_feature()
            if not active and args.command != "specify":
                print(f"\n❌ Error: No active feature found.", file=sys.stderr)
                print(f"   Run `sdd specify <feature-name>` to define and start a new feature.\n", file=sys.stderr)
                sys.exit(1)
            feature.update_phase(args.command)
        print(f"==> Active Phase: ({args.command})")
        print(f"Execute in your AI assistant the skill: /sdd-{args.command}")

    elif args.command == "finish":
        finish.finish_feature(create_pr=not args.no_pr, title=args.title)

    elif args.command == "quick":
        print(f"==> Executing SDD quick fix task: {' '.join(args.args)}")

    elif args.command == "reset":
        reset.reset(target=args.target, force=args.force, dry_run=args.dry_run)

    elif args.command in ["bridge", "adapter"]:
        bridge.generate_adapters(
            target_dir=args.target_dir,
            gen_all=args.all,
            claude=args.claude,
            copilot=args.copilot,
            cursor=args.cursor,
            gemini=args.gemini,
            agy=args.agy,
            chatgpt=args.chatgpt,
            windsurf=args.windsurf,
            interactive=args.interactive,
        )

    elif args.command == "memory":
        if args.subcmd == "init": memory.init(args.args[0] if args.args else ".")
        elif args.subcmd == "read": memory.read(args.args[0] if args.args else ".")
        elif args.subcmd == "consolidate": memory.consolidate(args.args[0] if args.args else ".")

    elif args.command == "parse":
        parser.parse(args.input, args.output)

    elif args.command == "run":
        cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
        ret = runner.run_in_worktree(cmd, args.repo, args.branch, args.cleanup)
        sys.exit(ret)

    elif args.command == "verify":
        payload = verify.run_verification(target_dir=args.dir)
        if args.json:
            print(payload.to_json())
        else:
            print("==> SDD Automated Verification Result")
            print(f"    Status:              {'PASS' if payload.passed else 'FAIL'}")
            details = payload.details or {}
            print(f"    Target Directory:    {details.get('target_dir', args.dir)}")
            print(f"    Technology Stack:    {details.get('stack', 'unknown')}")
            print("    --------------------------------------------------")
            print(f"    Linter Status:       {payload.linter_status}")
            print(f"    Test Suite Status:   {payload.test_status}")
            print(f"    Confirmation Read:   {payload.confirmation_read_status}")
            print(f"    Security Audit:      {payload.security_status}")
            if payload.remediation_instructions:
                print(f"    Remediation Fix:     {payload.remediation_instructions}")

    elif args.command == "hook":
        tool_args_parsed = args.tool_args
        if args.tool_args:
            try:
                tool_args_parsed = json.loads(args.tool_args)
            except Exception:
                tool_args_parsed = args.tool_args

        if args.event == "pre-tool":
            approved, reason = hooks.handle_pre_tool_event(
                tool_name=args.tool_name,
                tool_args=tool_args_parsed,
            )
            res = {"approved": approved, "reason": reason}
            print(json.dumps(res, indent=2))
        elif args.event == "post-tool":
            res = hooks.handle_post_tool_event(
                tool_name=args.tool_name,
                tool_args=tool_args_parsed,
                target_dir=args.dir,
            )
            print(json.dumps(res, indent=2))

    elif args.command == "gate":
        from pathlib import Path
        if args.subcmd == "snapshot":
            out_path = Path(args.output) if args.output else None
            snapshot = quality_gate.capture_baseline(output_path=out_path)
            memory.log_task_event("GATE", "HARNESS", "Captured baseline snapshot", f"Captured baseline snapshot with {snapshot.total_tests} tests")
            if args.json:
                print(snapshot.to_json())
            else:
                print("==> SDD Quality Gate: Baseline Snapshot Captured")
                print(f"    Timestamp:       {snapshot.timestamp}")
                print(f"    Total Tests:     {snapshot.total_tests} ({snapshot.passed_tests} passed, {snapshot.skipped_tests} skipped)")
                print(f"    Entry Points:    {len(snapshot.entry_points)}")
                print(f"    Public Contracts:{len(snapshot.public_contracts)}")
        elif args.subcmd == "check":
            b_path = Path(args.baseline) if args.baseline else None
            gate_res = quality_gate.run_gate_check(baseline_path=b_path, phase=args.phase)
            memory.log_task_event("GATE", "HARNESS", f"Quality gate check ({args.phase})", f"Phase '{args.phase}' check passed={gate_res.passed}")
            if args.json:
                print(gate_res.to_json())
            else:
                print(f"==> SDD Quality Gate: Check ({args.phase})")
                print(f"    Result:          {'✅ PASS' if gate_res.passed else '❌ FAIL'}")
                print(f"    Test Status:     {gate_res.test_result.status} (Passed: {gate_res.test_result.current_passed}/{gate_res.test_result.baseline_passed})")
                print(f"    Entry Points:    {'✅ OK' if gate_res.entry_point_result.passed else f'❌ FAIL ({len(gate_res.entry_point_result.failed)} failed)'}")
                print(f"    Public Contracts:{'✅ OK' if gate_res.contract_result.passed else f'❌ FAIL ({len(gate_res.contract_result.missing_symbols)} modules with missing symbols)'}")
                if not gate_res.passed:
                    if gate_res.test_result.regressions:
                        print(f"    Regressions:     {gate_res.test_result.regressions}")
                    if gate_res.entry_point_result.failed:
                        print(f"    Broken Entry Points: {gate_res.entry_point_result.failed}")
                    if gate_res.contract_result.missing_symbols:
                        print(f"    Missing Symbols: {gate_res.contract_result.missing_symbols}")
                    sys.exit(1)

    elif args.command == "sync":
        sync.sync_sdd(target_dir=args.dir, quiet=args.quiet)

    elif args.command == "mcp":
        from sdd_engine.mcp.server import run_mcp_server
        run_mcp_server(project_root=args.dir)

    elif args.command == "match-rules":
        from sdd_engine.core.rule_matcher import match_rules_for_files
        target_f = (args.files or []) + (getattr(args, "files_flag", None) or [])
        res = match_rules_for_files(target_files=target_f, target_dir=args.dir)
        if args.json:
            print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
        elif args.render:
            print(res.render_context())
        else:
            print("==> SDD Dynamic Rule Matching & Context Budgeting")
            print(f"    Target Files:             {len(res.matched_files)} ({', '.join(res.matched_files) or 'all'})")
            print(f"    Global Rules:             {len(res.global_rules)}")
            print(f"    Active Scoped Rules:      {len(res.matched_scoped_rules)} ({', '.join([r.name for r in res.matched_scoped_rules])})")
            print(f"    Unmatched Scoped Rules:   {len(res.unmatched_scoped_rules)}")
            print(f"    Total Catalog Budget:     ~{res.total_catalog_tokens} tokens")
            print(f"    Injected Prompt Budget:   ~{res.injected_tokens} tokens")
            print(f"    Estimated Token Savings:  ~{res.saved_tokens} tokens ({res.savings_percentage:.1f}%)")

    else:
        argp.print_help()

if __name__ == "__main__":
    main()
