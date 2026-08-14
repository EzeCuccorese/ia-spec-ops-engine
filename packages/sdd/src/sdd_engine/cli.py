import argparse
import json
import sys
from pathlib import Path

from sdd_engine import (
    feature,
    memory,
    parser,
    runner,
    reset,
    analyzer,
    harness,
    verify,
    hooks,
    quality_gate,
    revoke,
    sync,
    constitution,
    global_skills,
    finish,
    bridge,
)
from sdd_engine.exceptions import SDDError




class SpanishArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser providing Spanish error formatting and helpful usage prompts."""

    def error(self, message: str):
        sys.stderr.write(f"\n❌ Error de parámetros: {message}\n\n")
        self.print_help(sys.stderr)
        sys.exit(2)


def main():
    try:
        _run_cli()
    except (SDDError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _run_cli():
    argp = SpanishArgumentParser(
        description="""Specification-Driven Development (SDD) Manager CLI — Gestor de Desarrollo Guiado por Especificaciones

Ciclo de Vida Estricto de 8 Fases:
  1. sdd specify   ➜ Fase 1: Especificación funcional (spec.md)
  2. sdd clarify   ➜ Fase 2: Resolución de ambigüedades y auditoría (clarify.md)
  3. sdd plan      ➜ Fase 3: Blueprint técnico y contratos (plan.md)
  4. sdd checklist ➜ Fase 4: Quality Gates y Definition of Done (checklist.md)
  5. sdd tasks     ➜ Fase 5: Desglose atomizado de tareas ejecutables (tasks.md)
  6. sdd analyze   ➜ Fase 6: Auditoría estática de consistencia cruzada
  7. sdd exec      ➜ Fase 7: Ejecución iterativa multi-agente (Worker + QA)
  8. sdd converge  ➜ Fase 8: Verificación final de convergencia y Gherkin

* Para correcciones rápidas de bugs o hotfixes, usa: `sdd quick`
* Para configurar adaptadores de IA (Antigravity, Claude, Copilot, Cursor, etc.), usa: `sdd adapter` o `sdd bridge`
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = argp.add_subparsers(dest="command", help="Comandos disponibles de SDD")

    # Harness
    ph = sub.add_parser("harness", help="Orquestador del arnés de ejecución multi-agente SDD")
    ph.add_argument("subcmd", choices=["run", "status", "next", "log-worker", "log-qa"])
    ph.add_argument("--feature", help="Nombre de la característica destino")
    ph.add_argument("--max-retries", type=int, default=3, help="Límite de reintentos automáticos")
    ph.add_argument("--task-id", help="ID de tarea para registro")
    ph.add_argument("--summary", help="Resumen para registro de rol")
    ph.add_argument("--details", default="", help="Texto o diff detallado")
    ph.add_argument("--passed", action="store_true", help="Bandera de aprobación QA")

    # Init
    pi = sub.add_parser("init", help="Inicializar espacio de trabajo SDD en el proyecto (con Constitución)")
    pi.add_argument("dir", nargs="?", default=".", help="Directorio destino del proyecto")
    pi.add_argument("--interactive", "-i", action="store_true", help="Seleccionar agentes de IA de forma interactiva")
    pi.add_argument("--all", action="store_true", help="Configurar adaptadores para todos los agentes de IA")
    pi.add_argument("--restore-backup", action="store_true", help="Restaurar especificaciones e historial desde el respaldo previo .specify-backup-*")
    pi.add_argument("--claude", action="store_true")
    pi.add_argument("--copilot", action="store_true")
    pi.add_argument("--cursor", action="store_true")
    pi.add_argument("--gemini", action="store_true")
    pi.add_argument("--agy", action="store_true")
    pi.add_argument("--chatgpt", action="store_true")
    pi.add_argument("--windsurf", action="store_true")

    # Feature
    pf = sub.add_parser("feature", help="Establecer, listar o consultar las características (features) del repositorio")
    pf.add_argument("subcmd", nargs="?", help="Subcomando para gestión de feature o nombre de feature a activar")
    pf.add_argument("--from-branch", "-b", help="Rama base de la cual partir el nuevo Worktree (ej: main, develop)")
    pf.add_argument("args", nargs="*", help="Argumentos para el subcomando")

    # Lifecycle Phases
    phase_help = {
        "specify": "Fase 1: Define la especificación funcional (spec.md) con requerimientos, historias y Gherkin",
        "clarify": "Fase 2: Audita y resuelve ambigüedades, supuestos y casos borde en spec.md (clarify.md)",
        "plan": "Fase 3: Diseña la solución técnica, contratos de datos (Zod/DTOs) y diagramas Mermaid (plan.md)",
        "checklist": "Fase 4: Establece las Quality Gates, Definition of Done y pruebas requeridas (checklist.md)",
        "tasks": "Fase 5: Desglosa el plan técnico en tareas ejecutables ordenadas en 4 pilares (tasks.md)",
        "analyze": "Fase 6: Realiza auditoría estática de consistencia cruzada entre spec.md, plan.md, checklist.md y tasks.md",
        "exec": "Fase 7: Inicia la ejecución iterativa de tareas con el arnés multi-agente Worker y QA Reviewer",
        "converge": "Fase 8: Valida la convergencia final, ejecutando suite de pruebas, checklist y criterios Gherkin",
        "quick": "Ruta acelerada acotada para correcciones de bugs, parches menores o hotfixes (spec-quick.md)",
    }

    for cmd, htext in phase_help.items():
        sp = sub.add_parser(cmd, help=htext)
        sp.add_argument("--from-branch", "-b", help="Rama base de la cual partir el nuevo Worktree (ej: main, develop)")
        sp.add_argument("args", nargs="*", help="Argumentos opcionales de la fase (ej: nombre de la feature)")

    # Utils
    pa = sub.add_parser("audit", help="Auditar cumplimiento de SDD en el repositorio")
    pa.add_argument("args", nargs="*")

    pr = sub.add_parser("reset", help="Reinicio global de entorno y worktrees")
    pr.add_argument("--force", "-f", action="store_true")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--target", default="all", choices=["all", "cache", "worktrees", "repos"])

    # Bridge / Adapter
    for bcmd in ["bridge", "adapter"]:
        pb = sub.add_parser(bcmd, help="Generar y configurar adaptadores Multi-IA nativos (Antigravity, Claude, Copilot, Cursor, etc.)")
        pb.add_argument("--interactive", "-i", action="store_true", help="Seleccionar agentes interactivamente")
        pb.add_argument("--all", action="store_true", help="Configurar adaptadores para todos los agentes de IA")
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
        prv = sub.add_parser(rcmd, help="Revocar y remover la configuración de SDD y adaptadores IA del proyecto con respaldo automático")
        prv.add_argument("dir", nargs="?", default=".", help="Directorio del proyecto")
        prv.add_argument("--force", "-f", action="store_true", help="Forzar remoción sin confirmación interactiva")
        prv.add_argument("--no-backup", action="store_true", help="Omitir la creación del directorio de respaldo .specify-backup-*")

    # Finish / PR
    pfsh = sub.add_parser("finish", help="Finalizar ciclo SDD: push, PR con gh CLI, borrado de worktree y pull a main")
    pfsh.add_argument("--no-pr", action="store_true", help="Omitir la creación del PR en GitHub")
    pfsh.add_argument("--title", help="Título del Pull Request")

    # Global Skills Setup
    psg = sub.add_parser("setup-global", help="Instalar habilidades SDD globales para agentes de IA (~/.gemini/config/skills, ~/.agents/skills)")
    psg.add_argument("--force", "-f", action="store_true", default=True, help="Sobrescribir habilidades globales existentes")

    # Memory
    pm = sub.add_parser("memory", help="Herramientas de memoria del proyecto")
    pm.add_argument("subcmd", choices=["init", "log", "read", "consolidate"])
    pm.add_argument("args", nargs="*")

    # Parser
    pp = sub.add_parser("parse", help="Parsear especificación funcional")
    pp.add_argument("input")
    pp.add_argument("-o", "--output")

    # Runner
    prn = sub.add_parser("run", help="Ejecutar comando aislado en Git Worktree")
    prn.add_argument("--repo")
    prn.add_argument("--branch")
    prn.add_argument("--cleanup", action="store_true")
    prn.add_argument("cmd", nargs=argparse.REMAINDER)

    # Verify
    pv = sub.add_parser("verify", help="Ejecutar suite de verificación automatizada SDD")
    pv.add_argument("--dir", default=".", help="Directorio destino a verificar")
    pv.add_argument("--json", action="store_true", help="Salida en formato JSON")

    # Hook
    phk = sub.add_parser("hook", help="Ejecutar hooks de seguridad y verificación post-herramienta")
    phk.add_argument("event", choices=["pre-tool", "post-tool"], help="Tipo de evento de hook")
    phk.add_argument("--tool-name", default="", help="Nombre de la herramienta ejecutada")
    phk.add_argument("--tool-args", default=None, help="Argumentos de la herramienta")
    phk.add_argument("--dir", default=".", help="Directorio destino")

    # Quality Gate
    pg = sub.add_parser("gate", help="Arnés de Calidad: Captura de baseline y verificación de regresiones")
    pg.add_argument("subcmd", choices=["snapshot", "check"], help="Subcomando de gate")
    pg.add_argument("--output", "-o", help="Ruta JSON para guardar baseline snapshot")
    pg.add_argument("--baseline", "-b", help="Ruta JSON del baseline para verificación")
    pg.add_argument("--phase", default="pre-task", choices=["pre-task", "post-task", "convergence"], help="Fase de comprobación de gate")
    pg.add_argument("--json", action="store_true", help="Salida en formato JSON")

    # Sync
    psy = sub.add_parser("sync", help="Sincronizar instalación global de CLI e importar/actualizar adaptadores del proyecto")
    psy.add_argument("dir", nargs="?", default=".", help="Directorio destino")
    psy.add_argument("--quiet", "-q", action="store_true", help="Suprimir mensajes detallados")

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
                    ans = input(f"📦 Se detectó un backup previo ('{latest_b.name}').\n¿Deseas restaurar las especificaciones e historial anteriores? [y/N]: ").strip().lower()
                    if ans == "y":
                        do_restore = True
                except (EOFError, KeyboardInterrupt):
                    pass

            if do_restore:
                restored = revoke.restore_backup_specs(latest_b, target_dir=args.dir)
                if restored:
                    print(f"✅ Especificaciones e historial restaurados exitosamente desde {latest_b.name}")

        memory.init(args.dir)

        # Constitución del Proyecto (Spec-Kit Aligned)
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

        # Propagar inicialización SDD a todos los worktrees activos del repositorio
        active_wts = sync.get_active_repo_worktrees(args.dir)
        if active_wts:
            print(f"🔄 Se detectaron {len(active_wts)} worktree(s) activo(s) en el repositorio. Sincronizando SDD...")
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
                print(f"  ✅ SDD e IA inicializados en worktree: {wt.name}")

    elif args.command in ["remove", "revoke"]:
        success, bpath, removed = revoke.revoke_sdd_configuration(
            target_dir=args.dir,
            create_backup=not args.no_backup,
            force=args.force,
        )
        if success:
            if bpath:
                print(f"📦 Respaldo automático creado en: {bpath.name}")
            print(f"✅ Se removieron {len(removed)} elementos de configuración SDD e IA en {args.dir}")

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
                print(f"\n❌ Error: No hay ninguna característica (feature) activa.", file=sys.stderr)
                print(f"   Ejecuta `sdd specify <nombre-feature>` para definir e iniciar una nueva característica.\n", file=sys.stderr)
                sys.exit(1)
            feature.update_phase(args.command)
        print(f"==> Fase activa ({args.command})")
        print(f"Ejecuta en tu agente de IA la habilidad: /sdd-{args.command}")

    elif args.command == "finish":
        finish.finish_feature(create_pr=not args.no_pr, title=args.title)

    elif args.command == "quick":
        print(f"==> Ejecutando tarea rápida de corrección SDD: {' '.join(args.args)}")

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
            print("==> Resultado de Verificación Automatizada SDD")
            print(f"    Estado:              {'PASS' if payload.passed else 'FAIL'}")
            details = payload.details or {}
            print(f"    Directorio Destino:  {details.get('target_dir', args.dir)}")
            print(f"    Stack Tecnológico:   {details.get('stack', 'desconocido')}")
            print("    --------------------------------------------------")
            print(f"    Estado Linter:       {payload.linter_status}")
            print(f"    Estado Pruebas:      {payload.test_status}")
            print(f"    Lectura Confirmación:{payload.confirmation_read_status}")
            print(f"    Auditoría Seguridad: {payload.security_status}")
            if payload.remediation_instructions:
                print(f"    Instrucciones Fix:   {payload.remediation_instructions}")

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
                print("==> SDD Quality Gate: Snapshot Capturado")
                print(f"    Marca de tiempo: {snapshot.timestamp}")
                print(f"    Pruebas totales: {snapshot.total_tests} ({snapshot.passed_tests} aprobadas, {snapshot.skipped_tests} omitidas)")
                print(f"    Entry Points:    {len(snapshot.entry_points)}")
                print(f"    Módulos Públicos:{len(snapshot.public_contracts)}")
        elif args.subcmd == "check":
            b_path = Path(args.baseline) if args.baseline else None
            gate_res = quality_gate.run_gate_check(baseline_path=b_path, phase=args.phase)
            memory.log_task_event("GATE", "HARNESS", f"Quality gate check ({args.phase})", f"Phase '{args.phase}' check passed={gate_res.passed}")
            if args.json:
                print(gate_res.to_json())
            else:
                print(f"==> SDD Quality Gate: Check ({args.phase})")
                print(f"    Aprobado:        {'✅ PASS' if gate_res.passed else '❌ FAIL'}")
                print(f"    Estado Pruebas:  {gate_res.test_result.status} (Aprobadas: {gate_res.test_result.current_passed}/{gate_res.test_result.baseline_passed})")
                print(f"    Entry Points:    {'✅ OK' if gate_res.entry_point_result.passed else f'❌ FAIL ({len(gate_res.entry_point_result.failed)} fallidos)'}")
                print(f"    Contratos Pub:   {'✅ OK' if gate_res.contract_result.passed else f'❌ FAIL ({len(gate_res.contract_result.missing_symbols)} módulos con símbolos faltantes)'}")
                if not gate_res.passed:
                    if gate_res.test_result.regressions:
                        print(f"    Regresiones:     {gate_res.test_result.regressions}")
                    if gate_res.entry_point_result.failed:
                        print(f"    Entry Points Rotos: {gate_res.entry_point_result.failed}")
                    if gate_res.contract_result.missing_symbols:
                        print(f"    Símbolos Faltantes: {gate_res.contract_result.missing_symbols}")
                    sys.exit(1)

    elif args.command == "sync":
        sync.sync_sdd(target_dir=args.dir, quiet=args.quiet)

    else:
        argp.print_help()

if __name__ == "__main__":
    main()
