"""
workspace_engine.cli.kube — Paquete modular de Kubernetes para Workspace Engine.
"""

from workspace_engine.cli.kube.client import (
    is_kubectl_available,
    get_contexts,
    get_namespaces,
    find_pod,
    get_pod_env,
)
from workspace_engine.cli.kube.export import (
    write_secret_file,
    export_dotenv,
    export_set_env_sh,
)
from workspace_engine.cli.kube.tui import (
    select_context,
    select_operation,
)

__all__ = [
    "is_kubectl_available",
    "get_contexts",
    "get_namespaces",
    "find_pod",
    "get_pod_env",
    "write_secret_file",
    "export_dotenv",
    "export_set_env_sh",
    "select_context",
    "select_operation",
]
