"""
workspace_engine.cli.main — Entry point maestro y unificado para el CLI `ws`.

Reemplaza los 15 binarios aislados por un único comando unificado:
  ws generate
  ws edit
  ws worktree
  ws clean
  ws stop
  ws reset
  ws delete
  ws build
  ws deps
  ws java
  ws env-init
  ws env-load
  ws benchmark
  ws run-local
  ws kube
  ws doctor
"""

from __future__ import annotations

import argparse
import sys
import shutil
from rich.console import Console
from rich.table import Table

from devscripts_common import Color, log_info, log_error, log_success

console = Console()


def doctor_check() -> None:
    """Diagnóstico del entorno y herramientas del sistema."""
    table = Table(title="🏥 Diagnóstico del Entorno de Desarrollo (ws doctor)", border_style="green")
    table.add_column("Herramienta / Entorno", style="bold cyan")
    table.add_column("Estado", justify="center")
    table.add_column("Detalles", style="dim")

    tools = [
        ("git", "Gestor de versiones Git"),
        ("uv", "Gestor ultrarrápido de paquetes Python"),
        ("kubectl", "Controlador Kubernetes CLI"),
        ("java", "Java Development Kit"),
        ("mvn", "Apache Maven Build Tool"),
        ("node", "Node.js JavaScript Runtime"),
        ("npm", "Node Package Manager"),
        ("docker", "Docker Container Engine"),
    ]

    for tool, desc in tools:
        path = shutil.which(tool)
        if path:
            table.add_row(tool, "[green]✓ Disponible[/green]", f"{desc} ({path})")
        else:
            table.add_row(tool, "[yellow]⚠ No encontrado[/yellow]", desc)

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ws",
        description="Workspace Engine — Gestor Determinista de Workspaces, Repositorios y Entornos Locales.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponibles de Workspace Engine")

    # ws generate
    p_gen = subparsers.add_parser("generate", help="Generar un nuevo workspace multi-repositorio con Git worktrees")
    p_gen.add_argument("name", nargs="?", help="Nombre del workspace")
    p_gen.add_argument("repos", nargs="*", help="Repositorios iniciales (formato repo o repo:parent o repo@branch)")

    # ws edit
    p_edit = subparsers.add_parser("edit", help="Editar y agregar repositorios a un workspace existente")
    p_edit.add_argument("name", nargs="?", help="Nombre del workspace a editar")

    # ws worktree
    p_wt = subparsers.add_parser("worktree", help="Crear un git worktree de forma aislada")
    p_wt.add_argument("repo", help="Ruta o nombre del repositorio base")
    p_wt.add_argument("target", help="Ruta destino del nuevo worktree")
    p_wt.add_argument("branch", help="Nombre de la rama a asociar")

    # ws clean
    p_clean = subparsers.add_parser("clean", help="Limpiar dependencias y build artifacts en el workspace")
    p_clean.add_argument("target", nargs="?", default=".", help="Directorio del workspace")

    # ws stop
    p_stop = subparsers.add_parser("stop", help="Detener todos los servicios y procesos en ejecución del workspace")
    p_stop.add_argument("workspace", nargs="?", help="Nombre del workspace")

    # ws reset
    p_reset = subparsers.add_parser("reset", help="Resetear repositorios del workspace a estado limpio de upstream")
    p_reset.add_argument("workspace", nargs="?", help="Nombre del workspace")
    p_reset.add_argument("--force", "-f", action="store_true", help="Forzar reset descartando cambios locales")

    # ws delete
    p_del = subparsers.add_parser("delete", help="Eliminar workspaces y liberar worktrees asociados")
    p_del.add_argument("names", nargs="*", help="Nombres de los workspaces a eliminar")

    # ws build
    p_build = subparsers.add_parser("build", help="Compilar proyecto o microservicio detectando automáticamente el stack")
    p_build.add_argument("dir", nargs="?", default=".", help="Directorio del proyecto")

    # ws deps
    p_deps = subparsers.add_parser("deps", help="Instalar dependencias del proyecto (Gradle, Maven, NPM, etc.)")
    p_deps.add_argument("dir", nargs="?", default=".", help="Directorio del proyecto")

    # ws java
    p_java = subparsers.add_parser("java", help="Configurar versión de Java localmente")
    p_java.add_argument("version", nargs="?", help="Versión de Java (ej: 17, 21)")

    # ws env-init
    p_einit = subparsers.add_parser("env-init", help="Inicializar archivos de entorno para repositorios")
    p_einit.add_argument("repo", nargs="?", help="Nombre del repositorio")

    # ws env-load
    p_eload = subparsers.add_parser("env-load", help="Cargar e inspeccionar variables de entorno")
    p_eload.add_argument("repo", nargs="?", help="Nombre del repositorio")

    # ws benchmark
    p_bench = subparsers.add_parser("benchmark", help="Ejecutar benchmark de tests unitarios")
    p_bench.add_argument("dir", nargs="?", default=".", help="Directorio del proyecto")

    # ws run-local
    p_run = subparsers.add_parser("run-local", help="Orquestador de ejecución local de microservicios con monitor TUI")
    p_run.add_argument("--profile", "-p", help="Perfil de ejecución a cargar")
    p_run.add_argument("--env", "-e", help="Ambiente de variables destino (faf, granos, staging)")

    # ws kube
    p_kube = subparsers.add_parser("kube", help="Gestor de Kubernetes para extracción de entornos y shells")
    p_kube.add_argument("action", nargs="?", choices=["env", "logs", "shell"], help="Acción a ejecutar")

    # ws hooks
    p_hooks = subparsers.add_parser("hooks", help="Gestor de Git Hooks y Quality Gates Multi-Stack")
    p_hooks.add_argument("action", nargs="?", choices=["install", "status", "uninstall"], help="Acción a realizar")
    p_hooks.add_argument("--global", "-g", dest="is_global", action="store_true", help="Operar globalmente en ~/.githooks")
    p_hooks.add_argument("--dir", "-d", help="Directorio raíz del repositorio")
    p_hooks.add_argument("--force", "-f", action="store_true", default=True, help="Sobreescribir hooks existentes")

    # ws doctor
    subparsers.add_parser("doctor", help="Verificar estado y herramientas disponibles en el sistema")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Delegar a los submódulos correspondientes
    if args.command == "doctor":
        doctor_check()
    elif args.command == "hooks":
        from workspace_engine.cli.manage_hooks import main as hooks_main
        hooks_main()
    elif args.command == "generate":
        from workspace_engine.cli.generate_workspace import main as gen_main
        gen_main()
    elif args.command == "edit":
        from workspace_engine.cli.edit_workspace import main as edit_main
        edit_main()
    elif args.command == "worktree":
        from workspace_engine.cli.create_worktree import main as wt_main
        wt_main()
    elif args.command == "clean":
        from workspace_engine.cli.clean_workspace import main as clean_main
        clean_main()
    elif args.command == "stop":
        from workspace_engine.cli.stop_workspace import main as stop_main
        stop_main()
    elif args.command == "reset":
        from workspace_engine.cli.reset_repos import main as reset_main
        reset_main()
    elif args.command == "delete":
        from workspace_engine.cli.delete_workspaces import main as del_main
        del_main()
    elif args.command == "build":
        from workspace_engine.cli.build_project import main as build_main
        build_main()
    elif args.command == "deps":
        from workspace_engine.cli.install_deps import main as deps_main
        deps_main()
    elif args.command == "java":
        from workspace_engine.cli.set_java import main as java_main
        java_main()
    elif args.command == "env-init":
        from workspace_engine.cli.init_env import main as einit_main
        einit_main()
    elif args.command == "env-load":
        from workspace_engine.cli.load_env import main as eload_main
        eload_main()
    elif args.command == "benchmark":
        from workspace_engine.cli.unit_test_benchmark import main as bench_main
        bench_main()
    elif args.command == "run-local":
        from workspace_engine.run_local.main import main as run_main
        run_main()
    elif args.command == "kube":
        from workspace_engine.cli.kube_env import main as kube_main
        kube_main()


if __name__ == "__main__":
    main()
