"""
workspace_engine.cli.kube.main — Modular orchestrator for the `ws kube` command.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from workspace_engine.cli.kube.client import (
    find_pod,
    get_contexts,
    get_pod_env,
    is_kubectl_available,
)
from workspace_engine.cli.kube.export import export_dotenv, export_set_env_sh
from workspace_engine.cli.kube.tui import select_context, select_operation
from workspace_engine.common import log_error, log_info, log_success, log_warning

console = Console()


def handle_env_export(context: str | None, service_name: str | None = None) -> int:
    if not service_name:
        service_name = Prompt.ask("Enter the microservice or pod name")

    log_info(f"Looking up pod for '{service_name}'...")
    pod = find_pod(service_name, context=context)
    if not pod:
        log_error(f"No active pod found for service: {service_name}")
        return 1

    log_info(f"Extracting environment variables from pod: {pod}")
    env_vars = get_pod_env(pod, context=context)
    if not env_vars:
        log_warning("Could not extract variables, or the pod is empty.")
        return 1

    cwd = Path.cwd()
    dotenv_path = cwd / ".env"
    sh_path = cwd / "set-env.sh"

    export_dotenv(dotenv_path, env_vars)
    export_set_env_sh(sh_path, env_vars)
    log_success(f"Successfully extracted {len(env_vars)} variables.")
    return 0


def handle_logs(context: str | None, service_name: str | None = None) -> int:
    if not service_name:
        service_name = Prompt.ask("Enter the microservice or pod name")

    pod = find_pod(service_name, context=context)
    target = pod or service_name

    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(["logs", "--tail=100", "-f", target])

    log_info(f"Connecting to logs for {target}...")
    try:
        subprocess.run(cmd)
        return 0
    except KeyboardInterrupt:
        return 0


def handle_shell(context: str | None, service_name: str | None = None) -> int:
    if not service_name:
        service_name = Prompt.ask("Enter the microservice or pod name")

    pod = find_pod(service_name, context=context)
    target = pod or service_name

    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(["exec", "-it", target, "--", "sh"])

    log_info(f"Opening interactive shell on {target}...")
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        return 0


def main(action: str | None = None, service_name: str | None = None) -> int:
    """Main entry point for `ws kube`."""
    if not is_kubectl_available():
        log_error("kubectl is not available on PATH. Install kubectl to use this command.")
        return 1

    contexts = get_contexts()
    context = None
    if len(contexts) > 1:
        context = select_context(contexts)
    elif len(contexts) == 1:
        context = contexts[0]["name"]

    selected_action = action or select_operation()

    if selected_action == "env":
        return handle_env_export(context, service_name)
    elif selected_action == "logs":
        return handle_logs(context, service_name)
    elif selected_action == "shell":
        return handle_shell(context, service_name)
    else:
        log_error(f"Unsupported operation: {selected_action}")
        return 1


if __name__ == "__main__":
    op = sys.argv[1] if len(sys.argv) > 1 else None
    svc = sys.argv[2] if len(sys.argv) > 2 else None
    sys.exit(main(op, svc))
