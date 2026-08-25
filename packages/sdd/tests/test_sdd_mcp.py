"""
Tests unitarios para el servidor Model Context Protocol (MCP) de SDD Engine.
"""

import json
from pathlib import Path
import pytest

from sdd_engine.mcp.server import MCPServer, SERVER_INFO, PROTOCOL_VERSION


def test_mcp_server_initialize(tmp_path: Path):
    server = MCPServer(project_root=tmp_path)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert resp["result"]["serverInfo"] == SERVER_INFO
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_server_ping(tmp_path: Path):
    server = MCPServer(project_root=tmp_path)
    req = {"jsonrpc": "2.0", "id": "req-2", "method": "ping"}
    resp = server.handle_request(req)
    assert resp["id"] == "req-2"
    assert resp["result"] == {}


def test_mcp_server_list_tools(tmp_path: Path):
    server = MCPServer(project_root=tmp_path)
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    resp = server.handle_request(req)
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "sdd_verify" in tool_names
    assert "sdd_get_rules" in tool_names
    assert "sdd_feature_status" in tool_names
    assert "ws_clean" in tool_names


def test_mcp_server_call_tool_sdd_feature_status(tmp_path: Path):
    server = MCPServer(project_root=tmp_path)
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "sdd_feature_status",
            "arguments": {"target_dir": str(tmp_path)},
        },
    }
    resp = server.handle_request(req)
    assert resp["id"] == 4
    content = resp["result"]["content"]
    assert len(content) > 0
    data = json.loads(content[0]["text"])
    assert data["has_active_feature"] is False


def test_mcp_server_call_unknown_tool(tmp_path: Path):
    server = MCPServer(project_root=tmp_path)
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "non_existent_tool"},
    }
    resp = server.handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_mcp_server_resources_read_constitution(tmp_path: Path):
    const_dir = tmp_path / ".specify" / "constitution"
    const_dir.mkdir(parents=True)
    (const_dir / "constitution.md").write_text("# Test Constitution\n")

    server = MCPServer(project_root=tmp_path)
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "resources/read",
        "params": {"uri": "sdd://constitution"},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 6
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert "Test Constitution" in contents[0]["text"]
