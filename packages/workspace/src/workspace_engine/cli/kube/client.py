"""
workspace_engine.cli.kube.client — Deterministic kubectl interface and client for Kubernetes.
"""

from __future__ import annotations

import shutil
from typing import Any

from workspace_engine.common import log_warning, run_command_safe

KUBECTL_TIMEOUT = 30  # seconds


def is_kubectl_available() -> bool:
    """Checks whether the kubectl binary is available on the system PATH."""
    return shutil.which("kubectl") is not None


def get_contexts() -> list[dict[str, Any]]:
    """Returns the configured kubectl contexts."""
    if not is_kubectl_available():
        return []

    code, stdout, _ = run_command_safe(
        ["kubectl", "config", "get-contexts", "-o", "name"], timeout=KUBECTL_TIMEOUT
    )
    if code != 0 or not stdout.strip():
        return []

    contexts = []
    # Current context
    code_cur, cur_ctx, _ = run_command_safe(
        ["kubectl", "config", "current-context"], timeout=KUBECTL_TIMEOUT
    )
    current_name = cur_ctx.strip() if code_cur == 0 else ""

    for line in stdout.splitlines():
        ctx_name = line.strip()
        if ctx_name:
            contexts.append(
                {
                    "name": ctx_name,
                    "is_current": (ctx_name == current_name),
                }
            )
    return contexts


def find_pod(
    service_name: str, namespace: str | None = None, context: str | None = None
) -> str | None:
    """Finds the name of the Running pod of a microservice."""
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    if namespace:
        cmd.extend(["-n", namespace])
    cmd.extend(["get", "pods", "-o", "jsonpath={.items[*].metadata.name}"])

    code, stdout, _ = run_command_safe(cmd, timeout=KUBECTL_TIMEOUT)
    if code != 0 or not stdout.strip():
        return None

    pods = stdout.split()
    # Exact match or service-name prefix
    for pod in pods:
        if pod.startswith(f"{service_name}-") or pod == service_name:
            return pod
    return None


def get_pod_env(
    pod_name: str, namespace: str | None = None, context: str | None = None
) -> dict[str, str]:
    """Reads the environment variables of a Kubernetes pod."""
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    if namespace:
        cmd.extend(["-n", namespace])
    cmd.extend(["exec", pod_name, "--", "env"])

    code, stdout, stderr = run_command_safe(cmd, timeout=KUBECTL_TIMEOUT)
    if code != 0:
        log_warning(f"Could not read variables from {pod_name}: {stderr}")
        return {}

    env_vars: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()
    return env_vars
