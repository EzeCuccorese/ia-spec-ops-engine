"""
sdd_engine.mcp.server — Servidor nativo JSON-RPC 2.0 compatible con Model Context Protocol (MCP).

Expone herramientas y recursos de Devscripts (SDD y Workspace Engine) para asistentes
de IA como Claude Code, Cursor, Antigravity, VS Code y Windsurf.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from sdd_engine.core.utils import find_project_root
from sdd_engine.harness.verify import run_verification
from sdd_engine.lifecycle import constitution, feature
from sdd_engine.adapters.bridge import load_rules_catalog


SERVER_INFO = {
    "name": "devscripts-sdd-mcp",
    "version": "0.3.0",
}

PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    """Servidor MCP determinista basado en JSON-RPC 2.0 sobre stdio."""

    def __init__(self, project_root: Optional[Union[str, Path]] = None) -> None:
        self.project_root = Path(project_root).resolve() if project_root else find_project_root()
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._tool_handlers: Dict[str, Callable[..., Any]] = {}
        self._resources: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()
        self._register_default_resources()

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        self._tool_handlers[name] = handler

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str,
        mime_type: str = "text/plain",
    ) -> None:
        self._resources[uri] = {
            "uri": uri,
            "name": name,
            "description": description,
            "mimeType": mime_type,
        }

    def _register_default_tools(self) -> None:
        # 1. sdd_verify
        self.register_tool(
            name="sdd_verify",
            description="Ejecuta la suite de verificación automatizada SDD (linters, tests, post-mutation GET reads, escaneo de secretos y PII).",
            input_schema={
                "type": "object",
                "properties": {
                    "target_dir": {"type": "string", "description": "Directorio a verificar (opcional, default '.')"},
                    "modified_files": {"type": "array", "items": {"type": "string"}, "description": "Lista de archivos modificados para verificación acotada"},
                    "run_tests": {"type": "boolean", "default": True},
                    "run_linter": {"type": "boolean", "default": True},
                    "run_security": {"type": "boolean", "default": True},
                },
            },
            handler=self._handle_sdd_verify,
        )

        # 2. sdd_get_rules
        self.register_tool(
            name="sdd_get_rules",
            description="Obtiene el catálogo de reglas globales y específicas (scoped) aplicables al proyecto.",
            input_schema={
                "type": "object",
                "properties": {
                    "target_dir": {"type": "string", "description": "Directorio del proyecto"},
                },
            },
            handler=self._handle_sdd_get_rules,
        )

        # 3. sdd_feature_status
        self.register_tool(
            name="sdd_feature_status",
            description="Consulta el estado de la feature activa en SDD y sus artefactos generados.",
            input_schema={
                "type": "object",
                "properties": {
                    "target_dir": {"type": "string", "description": "Directorio del proyecto"},
                },
            },
            handler=self._handle_sdd_feature_status,
        )

        # 4. ws_clean
        self.register_tool(
            name="ws_clean",
            description="Limpia artefactos de compilación (.venv, node_modules, build/, target/, .pytest_cache) en el workspace de forma determinista.",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_dir": {"type": "string", "description": "Ruta del workspace a limpiar"},
                },
            },
            handler=self._handle_ws_clean,
        )

    def _register_default_resources(self) -> None:
        self.register_resource(
            uri="sdd://constitution",
            name="Constitución SDD del Proyecto",
            description="Reglas arquitectónicas, estándares de código y directrices fundamentales.",
            mime_type="text/markdown",
        )
        self.register_resource(
            uri="sdd://active-feature",
            name="Estado de Feature Activa",
            description="Metadatos en JSON de la feature activa en .specify/feature.json",
            mime_type="application/json",
        )

    def _handle_sdd_verify(self, **kwargs: Any) -> Dict[str, Any]:
        target_dir = kwargs.get("target_dir") or str(self.project_root)
        modified_files = kwargs.get("modified_files")
        run_tests = kwargs.get("run_tests", True)
        run_linter = kwargs.get("run_linter", True)
        run_security = kwargs.get("run_security", True)

        payload = run_verification(
            target_dir=target_dir,
            modified_files=modified_files,
            run_tests=run_tests,
            run_linter=run_linter,
            run_security=run_security,
        )
        return payload.to_dict()

    def _handle_sdd_get_rules(self, **kwargs: Any) -> Dict[str, Any]:
        target_dir = kwargs.get("target_dir") or str(self.project_root)
        global_rules, scoped_rules = load_rules_catalog(target_dir)
        return {
            "global_rules_count": len(global_rules),
            "scoped_rules_count": len(scoped_rules),
            "global_rules": [r.name for r in global_rules],
            "scoped_rules": [{"name": r.name, "globs": r.globs} for r in scoped_rules],
        }

    def _handle_sdd_feature_status(self, **kwargs: Any) -> Dict[str, Any]:
        target_dir = kwargs.get("target_dir") or str(self.project_root)
        feat_name = feature.get_active_feature(target_dir)
        return {
            "has_active_feature": feat_name is not None,
            "active_feature": feat_name,
        }

    def _handle_ws_clean(self, **kwargs: Any) -> Dict[str, Any]:
        ws_dir = kwargs.get("workspace_dir") or str(self.project_root)
        try:
            from workspace_engine.cli.clean_workspace import clean_workspace
            code = clean_workspace(Path(ws_dir))
            return {"status": "SUCCESS" if code == 0 else "ERROR", "code": code}
        except ImportError:
            return {"status": "SKIPPED", "message": "workspace_engine no disponible"}

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Procesa una solicitud JSON-RPC 2.0 y retorna la respuesta correspondiente."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": SERVER_INFO,
                },
            }

        elif method == "notifications/initialized":
            return None

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": list(self._tools.values())},
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if tool_name not in self._tool_handlers:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Herramienta no encontrada: {tool_name}",
                    },
                }

            try:
                result = self._tool_handlers[tool_name](**tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2, ensure_ascii=False)
                                if isinstance(result, (dict, list))
                                else str(result),
                            }
                        ]
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"Error ejecutando herramienta: {str(e)}"}],
                    },
                }

        elif method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": list(self._resources.values())},
            }

        elif method == "resources/read":
            uri = params.get("uri", "")
            if uri == "sdd://constitution":
                content = constitution.read_constitution(self.project_root) or "# Sin constitución definida"
                mime_type = "text/markdown"
            elif uri == "sdd://active-feature":
                feat_file = self.project_root / ".specify" / "feature.json"
                content = feat_file.read_text(encoding="utf-8") if feat_file.exists() else "{}"
                mime_type = "application/json"
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32002, "message": f"Recurso no encontrado: {uri}"},
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": mime_type,
                            "text": content,
                        }
                    ]
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Método no soportado: {method}"},
        }


def run_mcp_server(project_root: Optional[Union[str, Path]] = None) -> None:
    """Loop principal del servidor MCP sobre stdio."""
    server = MCPServer(project_root=project_root)
    # MCP sobre stdio lee línea por línea JSON-RPC
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = server.handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "JSON Parse Error"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
