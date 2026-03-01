"""Integration tests for MCP session lifecycle using a mock server subprocess."""

import sys

import pytest

from koclaw_agent.mcp_host.server_manager import McpServerManager

MOCK_MCP_SERVER = '''\
import json
import sys


def read_message():
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def write_message(msg):
    sys.stdout.write(json.dumps(msg) + "\\n")
    sys.stdout.flush()


def handle_request(req):
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-echo", "version": "0.1.0"},
            },
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo input text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            },
        }
    elif method == "tools/call":
        text = req["params"]["arguments"].get("text", "")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"echo: {text}"}],
                "isError": False,
            },
        }
    elif method == "notifications/initialized":
        return None
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown: {method}"},
        }


if __name__ == "__main__":
    while True:
        msg = read_message()
        if msg is None:
            break
        resp = handle_request(msg)
        if resp is not None:
            write_message(resp)
'''


@pytest.fixture()
def mock_server_script(tmp_path):
    script = tmp_path / "mock_mcp_server.py"
    script.write_text(MOCK_MCP_SERVER)
    return str(script)


@pytest.mark.asyncio
async def test_connect_and_list_tools(mock_server_script):
    manager = McpServerManager()
    manager.load_configs({
        "test-echo": {"command": sys.executable, "args": [mock_server_script]},
    })
    await manager.connect_all()
    try:
        tools = await manager.list_all_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"
        assert tools[0]["_mcp_server"] == "test-echo"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_call_tool(mock_server_script):
    manager = McpServerManager()
    manager.load_configs({
        "test-echo": {"command": sys.executable, "args": [mock_server_script]},
    })
    await manager.connect_all()
    try:
        result = await manager.call_tool("echo", {"text": "hello"})
        assert "echo: hello" in result
    finally:
        await manager.shutdown()
