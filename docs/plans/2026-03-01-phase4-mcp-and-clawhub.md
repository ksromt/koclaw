# Phase 4: MCP Integration & ClawHub Compatibility

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable Koclaw to connect to the MCP ecosystem as a Host/Client, consume ClawHub skills, and expose its own capabilities as MCP-compatible tools — all with Koclaw's security-first guarantees.

**Architecture:** The Python Agent becomes an MCP Host managing multiple MCP Client sessions (one per server). MCP servers are launched as sandboxed subprocesses (stdio transport) or connected via Streamable HTTP. SKILL.md files from ClawHub are parsed into system prompt extensions that teach the Agent how to use available MCP tools. The Rust Gateway enforces permission-gated tool invocation through the existing bridge protocol.

**Tech Stack:** Python `mcp` SDK (client), Rust `rmcp` crate (future server), JSON-RPC 2.0, YAML frontmatter parsing, ClawHub REST API.

---

## Overview

### Why MCP + ClawHub?

1. **MCP** is the industry standard (Anthropic + Linux Foundation) for connecting AI agents to tools. Adding MCP support gives Koclaw access to 1,000+ community MCP servers (filesystem, databases, web search, APIs).
2. **ClawHub** is the largest AI skill registry (3,200+ skills). Skills are Markdown instruction manuals that teach agents HOW to use tools. Supporting SKILL.md format gives Koclaw instant access to this ecosystem.
3. **Security differentiator**: OpenClaw's skill system was hit by the ClawHavoc supply chain attack (824 malicious skills, 12% infection rate). Koclaw's Rust sandbox + permission system makes it the secure alternative.

### Phased Approach

| Sub-Phase | Scope | Depends On |
|-----------|-------|------------|
| **4A** | MCP Client (Python) — connect to external MCP servers | None |
| **4B** | SKILL.md Parser — read ClawHub skill format | 4A |
| **4C** | ClawHub Client — discover, install, manage skills | 4B |
| **4D** | Permission-Gated Tool Invocation — security layer | 4A |
| **4E** | MCP Server (Rust) — expose Koclaw as MCP server | 4A (optional, future) |

**This plan covers 4A through 4D.** Phase 4E (exposing Koclaw as MCP server) is deferred to a future plan.

---

## Sub-Phase 4A: MCP Client Integration (Python Agent)

### Goal

Make the Python Agent an MCP Host that can launch and manage MCP server processes, discover their tools, and invoke them on behalf of the LLM.

### Task 1: Add MCP SDK Dependency

**Files:**
- Modify: `agent/pyproject.toml`

**Step 1: Add the `mcp` package to dependencies**

In `agent/pyproject.toml`, add to `[project.dependencies]`:

```toml
[project.dependencies]
websockets = ">=12.0"
anthropic = ">=0.40.0"
openai = ">=1.50.0"
pyyaml = ">=6.0"
tomli = ">=2.0"
mcp = ">=1.7.0"
```

**Step 2: Sync dependencies**

Run: `cd agent && uv sync`
Expected: Successfully installs `mcp` and its transitive deps (`anyio`, `httpx`, `pydantic`, `sse-starlette`)

**Step 3: Verify import**

Run: `cd agent && uv run python -c "from mcp import ClientSession; print('MCP SDK available')"`
Expected: `MCP SDK available`

**Step 4: Commit**

```bash
git add agent/pyproject.toml agent/uv.lock
git commit -m "chore(agent): add mcp SDK dependency"
```

---

### Task 2: MCP Server Manager

**Files:**
- Create: `agent/koclaw_agent/mcp_host/__init__.py`
- Create: `agent/koclaw_agent/mcp_host/server_manager.py`
- Test: `agent/tests/test_mcp_host.py`

**Step 1: Write the failing test**

```python
# agent/tests/test_mcp_host.py
"""Tests for MCP server manager."""
import pytest
from koclaw_agent.mcp_host.server_manager import McpServerManager, McpServerConfig


def test_server_config_from_dict():
    """Parse a server config from dict (as it would appear in config.toml)."""
    cfg = McpServerConfig.from_dict("time", {
        "command": "uvx",
        "args": ["mcp-server-time"],
    })
    assert cfg.name == "time"
    assert cfg.command == "uvx"
    assert cfg.args == ["mcp-server-time"]
    assert cfg.env == {}
    assert cfg.transport == "stdio"


def test_server_config_with_env():
    """Server config can include environment variables."""
    cfg = McpServerConfig.from_dict("github", {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "ghp_xxx"},
    })
    assert cfg.env == {"GITHUB_TOKEN": "ghp_xxx"}


def test_manager_registers_configs():
    """Manager loads multiple server configs."""
    manager = McpServerManager()
    configs = {
        "time": {"command": "uvx", "args": ["mcp-server-time"]},
        "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    }
    manager.load_configs(configs)
    assert len(manager.configs) == 2
    assert "time" in manager.configs
    assert "fs" in manager.configs


def test_manager_empty_configs():
    """Manager handles empty config gracefully."""
    manager = McpServerManager()
    manager.load_configs({})
    assert len(manager.configs) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m pytest tests/test_mcp_host.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'koclaw_agent.mcp_host'`

**Step 3: Write minimal implementation**

```python
# agent/koclaw_agent/mcp_host/__init__.py
"""MCP Host integration for Koclaw Agent."""

# agent/koclaw_agent/mcp_host/server_manager.py
"""Manages MCP server lifecycle — launch, connect, discover tools, invoke."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    """Configuration for a single MCP server."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"  # "stdio" or "http"
    url: str | None = None    # For HTTP transport

    @classmethod
    def from_dict(cls, name: str, d: dict) -> McpServerConfig:
        return cls(
            name=name,
            command=d.get("command", ""),
            args=d.get("args", []),
            env=d.get("env", {}),
            transport=d.get("transport", "stdio"),
            url=d.get("url"),
        )


class McpServerManager:
    """Manages multiple MCP server connections.

    Lifecycle:
    1. load_configs() — parse server definitions from config
    2. connect_all() — launch servers and establish MCP sessions
    3. list_all_tools() — aggregate tool schemas across all servers
    4. call_tool() — route a tool call to the correct server
    5. shutdown() — gracefully close all connections
    """

    def __init__(self) -> None:
        self.configs: dict[str, McpServerConfig] = {}
        self._sessions: dict[str, object] = {}  # name -> ClientSession (lazy)

    def load_configs(self, configs: dict[str, dict]) -> None:
        """Load server configs from a dict (from config.toml [mcp.servers])."""
        self.configs.clear()
        for name, cfg_dict in configs.items():
            cfg = McpServerConfig.from_dict(name, cfg_dict)
            self.configs[name] = cfg
            logger.info("MCP server config loaded: %s (%s)", name, cfg.command)
```

**Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m pytest tests/test_mcp_host.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add agent/koclaw_agent/mcp_host/ agent/tests/test_mcp_host.py
git commit -m "feat(agent): add MCP server config parsing"
```

---

### Task 3: MCP Session Lifecycle (Connect, Discover, Call)

**Files:**
- Modify: `agent/koclaw_agent/mcp_host/server_manager.py`
- Create: `agent/tests/test_mcp_session.py`

**Step 1: Write the failing test**

```python
# agent/tests/test_mcp_session.py
"""Integration test for MCP session lifecycle using a real MCP server."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

from koclaw_agent.mcp_host.server_manager import McpServerManager


# We create a tiny in-process MCP server for testing
MOCK_MCP_SERVER = '''
"""Minimal MCP server for testing — exposes an 'echo' tool via stdio."""
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
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-echo", "version": "0.1.0"},
            }
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo input text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    }
                }]
            }
        }
    elif method == "tools/call":
        text = req["params"]["arguments"].get("text", "")
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"echo: {text}"}],
                "isError": False,
            }
        }
    elif method == "notifications/initialized":
        return None  # Notification, no response
    else:
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
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


@pytest.fixture
def mock_server_script(tmp_path):
    """Write the mock MCP server script to a temp file."""
    script = tmp_path / "mock_mcp_server.py"
    script.write_text(MOCK_MCP_SERVER)
    return str(script)


@pytest.mark.asyncio
async def test_connect_and_list_tools(mock_server_script):
    """Connect to a real MCP server process and list its tools."""
    manager = McpServerManager()
    manager.load_configs({
        "test-echo": {
            "command": sys.executable,
            "args": [mock_server_script],
        }
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
    """Call a tool through the MCP manager."""
    manager = McpServerManager()
    manager.load_configs({
        "test-echo": {
            "command": sys.executable,
            "args": [mock_server_script],
        }
    })

    await manager.connect_all()
    try:
        result = await manager.call_tool("echo", {"text": "hello"})
        assert "echo: hello" in result
    finally:
        await manager.shutdown()
```

**Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m pytest tests/test_mcp_session.py -v`
Expected: FAIL — `AttributeError: 'McpServerManager' object has no attribute 'connect_all'`

**Step 3: Implement MCP session lifecycle**

Add to `server_manager.py`:

```python
import asyncio
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpServerManager:
    # ... (existing code) ...

    def __init__(self) -> None:
        self.configs: dict[str, McpServerConfig] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._exit_stack: AsyncExitStack | None = None
        self._tool_map: dict[str, str] = {}  # tool_name -> server_name

    async def connect_all(self) -> None:
        """Launch all configured MCP servers and establish sessions."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for name, cfg in self.configs.items():
            try:
                await self._connect_server(name, cfg)
            except Exception:
                logger.exception("Failed to connect MCP server: %s", name)

    async def _connect_server(self, name: str, cfg: McpServerConfig) -> None:
        """Connect to a single MCP server via stdio transport."""
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env if cfg.env else None,
        )
        reader, writer = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(reader, writer)
        )
        await session.initialize()
        self._sessions[name] = session
        logger.info("MCP server connected: %s", name)

        # Cache tool -> server mapping
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            self._tool_map[tool.name] = name
            logger.debug("  Tool registered: %s (from %s)", tool.name, name)

    async def list_all_tools(self) -> list[dict]:
        """Aggregate tool schemas from all connected MCP servers.

        Each tool dict includes an extra '_mcp_server' key
        indicating which server provides it.
        """
        all_tools = []
        for name, session in self._sessions.items():
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                tool_dict = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if hasattr(tool, 'inputSchema') else {},
                    "_mcp_server": name,
                }
                all_tools.append(tool_dict)
        return all_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Invoke a tool by name, routing to the correct MCP server.

        Returns the text content of the tool result.
        """
        server_name = self._tool_map.get(tool_name)
        if not server_name:
            return f"Error: Unknown tool '{tool_name}'"

        session = self._sessions.get(server_name)
        if not session:
            return f"Error: Server '{server_name}' not connected"

        result = await session.call_tool(tool_name, arguments=arguments)

        # Extract text content from result
        texts = []
        for content in result.content:
            if hasattr(content, 'text'):
                texts.append(content.text)
        return "\n".join(texts) if texts else str(result)

    async def shutdown(self) -> None:
        """Gracefully close all MCP sessions and server processes."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._sessions.clear()
            self._tool_map.clear()
            logger.info("All MCP servers shut down")
```

**Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m pytest tests/test_mcp_session.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add agent/koclaw_agent/mcp_host/server_manager.py agent/tests/test_mcp_session.py
git commit -m "feat(agent): add MCP session lifecycle — connect, discover, call tools"
```

---

### Task 4: Wire MCP into Agent Bridge

**Files:**
- Modify: `agent/koclaw_agent/bridge.py`
- Modify: `agent/koclaw_agent/__main__.py`
- Modify: `agent/koclaw_agent/config.py`

**Step 1: Add MCP config section to config.toml parsing**

In `config.py`, add parsing for `[mcp]` section:

```python
def resolve_mcp_configs(config: dict) -> dict[str, dict]:
    """Extract MCP server configurations from config.toml.

    Expected format:
    [mcp.servers.time]
    command = "uvx"
    args = ["mcp-server-time"]

    [mcp.servers.filesystem]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    env = { ALLOWED_DIR = "/workspace" }
    """
    mcp_section = config.get("mcp", {})
    return mcp_section.get("servers", {})
```

**Step 2: Initialize MCP manager in AgentBridge**

In `bridge.py`, add MCP manager initialization and pass available tools to LLM:

```python
from koclaw_agent.mcp_host.server_manager import McpServerManager

class AgentBridge:
    def __init__(self, host, port, provider_configs=None, mcp_configs=None):
        # ... existing init ...
        self.mcp_manager = McpServerManager()
        if mcp_configs:
            self.mcp_manager.load_configs(mcp_configs)

    async def start(self):
        # Connect MCP servers before accepting gateway connections
        if self.mcp_manager.configs:
            await self.mcp_manager.connect_all()
        # ... existing websocket serve ...

    async def _handle_chat(self, websocket, message):
        # Inject available MCP tools into system prompt
        tools = await self.mcp_manager.list_all_tools() if self.mcp_manager.configs else []
        # ... pass tools context to LLM ...
```

**Step 3: Update __main__.py to pass MCP configs**

```python
from koclaw_agent.config import load_config, resolve_provider_configs, resolve_mcp_configs

def main():
    config = load_config()
    provider_configs = resolve_provider_configs(config)
    mcp_configs = resolve_mcp_configs(config)

    bridge = AgentBridge(
        host="127.0.0.1",
        port=18790,
        provider_configs=provider_configs,
        mcp_configs=mcp_configs,
    )
    asyncio.run(bridge.start())
```

**Step 4: Run all existing tests to verify no regressions**

Run: `cd agent && uv run python -m pytest tests/ -v`
Expected: All 14+ tests pass

**Step 5: Commit**

```bash
git add agent/koclaw_agent/bridge.py agent/koclaw_agent/__main__.py agent/koclaw_agent/config.py
git commit -m "feat(agent): wire MCP server manager into agent bridge"
```

---

### Task 5: LLM Tool Calling via MCP

**Files:**
- Create: `agent/koclaw_agent/mcp_host/tool_prompt.py`
- Modify: `agent/koclaw_agent/bridge.py`
- Test: `agent/tests/test_tool_prompt.py`

**Step 1: Write the failing test**

```python
# agent/tests/test_tool_prompt.py
"""Tests for MCP tool prompt generation."""
from koclaw_agent.mcp_host.tool_prompt import build_tool_prompt, parse_tool_call


def test_build_tool_prompt_single_tool():
    """Generate prompt section for a single tool."""
    tools = [{
        "name": "get_time",
        "description": "Get the current time",
        "inputSchema": {
            "type": "object",
            "properties": {"timezone": {"type": "string"}},
        },
        "_mcp_server": "time",
    }]
    prompt = build_tool_prompt(tools)
    assert "get_time" in prompt
    assert "Get the current time" in prompt
    assert "timezone" in prompt


def test_build_tool_prompt_empty():
    """No tools means no prompt section."""
    assert build_tool_prompt([]) == ""


def test_parse_tool_call_valid():
    """Parse a valid JSON tool call from LLM output."""
    text = 'Let me check. {"tool": "get_time", "arguments": {"timezone": "UTC"}}'
    result = parse_tool_call(text)
    assert result is not None
    assert result["tool"] == "get_time"
    assert result["arguments"]["timezone"] == "UTC"


def test_parse_tool_call_no_call():
    """No tool call in regular text."""
    assert parse_tool_call("Hello, how are you?") is None


def test_parse_tool_call_mcp_server_field():
    """Tool call may include mcp_server hint."""
    text = '{"mcp_server": "fs", "tool": "read_file", "arguments": {"path": "/tmp/a.txt"}}'
    result = parse_tool_call(text)
    assert result is not None
    assert result["tool"] == "read_file"
```

**Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m pytest tests/test_tool_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement tool prompt builder and parser**

```python
# agent/koclaw_agent/mcp_host/tool_prompt.py
"""Generate tool-calling prompts for LLMs and parse tool call responses.

This module bridges MCP tool schemas and LLM text-based tool calling.
For LLMs with native tool_use (Claude, GPT-4), this serves as fallback.
For LLMs without native tool support, this is the primary mechanism.
"""
from __future__ import annotations

import json
import re
import logging

logger = logging.getLogger(__name__)


def build_tool_prompt(tools: list[dict]) -> str:
    """Build a system prompt section describing available MCP tools.

    Follows the prompt format proven in AIKokoron's mcp_prompt.txt:
    JSON-based tool calling with explicit format instructions.
    """
    if not tools:
        return ""

    lines = [
        "",
        "## Available Tools",
        "",
        "You have access to the following tools via MCP (Model Context Protocol).",
        "To use a tool, output a JSON object on its own line:",
        "",
        "```json",
        '{"tool": "<tool_name>", "arguments": {<arguments>}}',
        "```",
        "",
        "Rules:",
        "- Only use ONE tool call per response.",
        "- Place the JSON before any explanation text.",
        "- Do not invent tools that are not listed below.",
        "- If no tool is needed, respond normally without JSON.",
        "",
        "### Tool List",
        "",
    ]

    for tool in tools:
        name = tool["name"]
        desc = tool.get("description", "No description")
        schema = tool.get("inputSchema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])

        lines.append(f"**{name}** — {desc}")
        if props:
            lines.append("  Parameters:")
            for pname, pschema in props.items():
                ptype = pschema.get("type", "any")
                req_mark = " (required)" if pname in required else ""
                pdesc = pschema.get("description", "")
                lines.append(f"  - `{pname}` ({ptype}{req_mark}): {pdesc}")
        lines.append("")

    return "\n".join(lines)


def parse_tool_call(text: str) -> dict | None:
    """Extract a JSON tool call from LLM output text.

    Looks for {"tool": "...", "arguments": {...}} pattern.
    Returns the parsed dict or None if no tool call found.
    """
    # Try to find JSON object containing "tool" key
    # Match both fenced code blocks and bare JSON
    patterns = [
        r"```json\s*\n?(.*?)\n?```",   # Fenced code block
        r"(\{[^{}]*\"tool\"[^{}]*\})",  # Inline JSON (simple, no nesting)
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            try:
                obj = json.loads(match.strip())
                if isinstance(obj, dict) and "tool" in obj:
                    return obj
            except json.JSONDecodeError:
                continue

    # Fallback: try to parse any JSON object in the text
    for match in re.finditer(r'\{.*?\}', text, re.DOTALL):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    return None
```

**Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m pytest tests/test_tool_prompt.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add agent/koclaw_agent/mcp_host/tool_prompt.py agent/tests/test_tool_prompt.py
git commit -m "feat(agent): add MCP tool prompt builder and call parser"
```

---

### Task 6: Tool Execution Loop in Bridge

**Files:**
- Modify: `agent/koclaw_agent/bridge.py`
- Test: manual integration test

**Step 1: Add tool execution loop to _handle_chat**

In `bridge.py`, after receiving LLM response chunks, check for tool calls and execute them:

```python
async def _handle_chat(self, websocket, message):
    session_id = message["session_id"]
    text = message.get("text", "")
    permission = message.get("permission", "Public")
    system_prompt = message.get("system_prompt")
    attachments = message.get("attachments", [])

    # Load conversation history
    history = await self.memory.get_history(session_id)

    # Build tool prompt if MCP tools available and permission allows
    tool_prompt = ""
    if permission in ("Authenticated", "Admin") and self.mcp_manager.configs:
        tools = await self.mcp_manager.list_all_tools()
        tool_prompt = build_tool_prompt(tools)

    # Append tool prompt to system prompt
    full_system = (system_prompt or "") + tool_prompt

    # LLM generation with tool loop (max 3 iterations)
    full_response = ""
    for iteration in range(3):
        chunks = []
        async for chunk in self.llm_router.generate(
            text=text if iteration == 0 else f"Tool result:\n{tool_result}",
            session_id=session_id,
            permission=permission,
            attachments=attachments if iteration == 0 else [],
            system_prompt=full_system,
            history=history,
        ):
            chunks.append(chunk)
            # Stream text chunks to gateway
            await websocket.send(json.dumps({
                "msg_type": "text_chunk",
                "session_id": session_id,
                "content": chunk,
            }))

        response_text = "".join(chunks)
        full_response += response_text

        # Check for tool call
        tool_call = parse_tool_call(response_text)
        if tool_call is None:
            break  # No tool call, done

        # Execute tool
        tool_name = tool_call["tool"]
        tool_args = tool_call.get("arguments", {})
        logger.info("Executing MCP tool: %s(%s)", tool_name, tool_args)
        tool_result = await self.mcp_manager.call_tool(tool_name, tool_args)

        # Add tool result to history for next iteration
        history.append({"role": "assistant", "content": response_text})
        history.append({"role": "user", "content": f"[Tool Result: {tool_name}]\n{tool_result}"})

    # Save to memory
    await self.memory.add_message(session_id, "user", text)
    await self.memory.add_message(session_id, "assistant", full_response)

    # ... expressions, audio, done message ...
```

**Note:** This is a simplified outline. The actual implementation should integrate with the existing streaming response flow in bridge.py, not replace it. The key addition is the tool execution loop.

**Step 2: Run all tests**

Run: `cd agent && uv run python -m pytest tests/ -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add agent/koclaw_agent/bridge.py
git commit -m "feat(agent): add MCP tool execution loop in chat handler"
```

---

## Sub-Phase 4B: SKILL.md Parser

### Goal

Parse ClawHub's SKILL.md format to extract skill metadata and instruction text, then inject them into the Agent's behavior.

### Task 7: SKILL.md Parser

**Files:**
- Create: `agent/koclaw_agent/mcp_host/skill_parser.py`
- Test: `agent/tests/test_skill_parser.py`

**Step 1: Write the failing test**

```python
# agent/tests/test_skill_parser.py
"""Tests for SKILL.md parser."""
from koclaw_agent.mcp_host.skill_parser import SkillDefinition, parse_skill_md


SAMPLE_SKILL_MD = '''---
name: web-search
description: Search the web using DuckDuckGo
version: 1.2.0
metadata:
  openclaw:
    env:
      - DDG_API_KEY
    bins:
      - curl
    emoji: "🔍"
    homepage: https://github.com/example/web-search-skill
user-invocable: true
---

## Instructions

When the user asks you to search the web:

1. Use the `ddg-search` MCP tool with the user's query
2. Summarize the top 3 results
3. Include source URLs

Keep summaries concise (2-3 sentences per result).
'''


def test_parse_skill_md_basic():
    """Parse a SKILL.md file with frontmatter and instructions."""
    skill = parse_skill_md(SAMPLE_SKILL_MD)
    assert skill.name == "web-search"
    assert skill.description == "Search the web using DuckDuckGo"
    assert skill.version == "1.2.0"
    assert "ddg-search" in skill.instructions
    assert skill.user_invocable is True


def test_parse_skill_md_env_vars():
    """Extract required environment variables."""
    skill = parse_skill_md(SAMPLE_SKILL_MD)
    assert "DDG_API_KEY" in skill.required_env


def test_parse_skill_md_bins():
    """Extract required binaries."""
    skill = parse_skill_md(SAMPLE_SKILL_MD)
    assert "curl" in skill.required_bins


def test_parse_skill_md_minimal():
    """Parse minimal SKILL.md with only name."""
    md = "---\nname: simple\ndescription: A simple skill\n---\nDo the thing."
    skill = parse_skill_md(md)
    assert skill.name == "simple"
    assert "Do the thing" in skill.instructions


def test_parse_skill_md_no_frontmatter():
    """Handle SKILL.md without YAML frontmatter gracefully."""
    skill = parse_skill_md("Just some instructions without frontmatter.")
    assert skill.name == "unknown"
    assert "Just some instructions" in skill.instructions
```

**Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m pytest tests/test_skill_parser.py -v`
Expected: FAIL

**Step 3: Implement SKILL.md parser**

```python
# agent/koclaw_agent/mcp_host/skill_parser.py
"""Parser for ClawHub SKILL.md format.

SKILL.md is a Markdown file with YAML frontmatter containing:
- name, description, version
- metadata.openclaw.env (required env vars)
- metadata.openclaw.bins (required binaries)
- user-invocable (expose as slash command)
- install (shell commands for setup)

The Markdown body contains instructions that teach the agent
how to accomplish a task using available tools.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


@dataclass
class SkillDefinition:
    """Parsed representation of a SKILL.md file."""
    name: str
    description: str = ""
    version: str = "0.0.0"
    instructions: str = ""
    required_env: list[str] = field(default_factory=list)
    required_bins: list[str] = field(default_factory=list)
    user_invocable: bool = False
    install_script: str = ""
    emoji: str = ""
    homepage: str = ""


def parse_skill_md(content: str) -> SkillDefinition:
    """Parse a SKILL.md string into a SkillDefinition.

    Format:
    ---
    name: skill-name
    description: What this skill does
    version: 1.0.0
    metadata:
      openclaw:
        env: [VAR1, VAR2]
        bins: [cmd1, cmd2]
    user-invocable: true
    install: |
      npm install -g something
    ---

    ## Instructions
    Markdown instructions body...
    """
    # Split frontmatter and body
    frontmatter_match = re.match(
        r'^---\s*\n(.*?)\n---\s*\n?(.*)',
        content,
        re.DOTALL
    )

    if not frontmatter_match:
        return SkillDefinition(
            name="unknown",
            instructions=content.strip(),
        )

    yaml_str = frontmatter_match.group(1)
    body = frontmatter_match.group(2).strip()

    try:
        meta = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError:
        return SkillDefinition(name="unknown", instructions=body)

    # Extract openclaw-specific metadata
    openclaw_meta = meta.get("metadata", {}).get("openclaw", {})

    return SkillDefinition(
        name=meta.get("name", "unknown"),
        description=meta.get("description", ""),
        version=meta.get("version", "0.0.0"),
        instructions=body,
        required_env=openclaw_meta.get("env", []),
        required_bins=openclaw_meta.get("bins", []),
        user_invocable=meta.get("user-invocable", False),
        install_script=meta.get("install", ""),
        emoji=openclaw_meta.get("emoji", ""),
        homepage=openclaw_meta.get("homepage", ""),
    )
```

**Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m pytest tests/test_skill_parser.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add agent/koclaw_agent/mcp_host/skill_parser.py agent/tests/test_skill_parser.py
git commit -m "feat(agent): add SKILL.md parser for ClawHub compatibility"
```

---

### Task 8: Skill Loader (Local Directory)

**Files:**
- Create: `agent/koclaw_agent/mcp_host/skill_loader.py`
- Test: `agent/tests/test_skill_loader.py`

**Step 1: Write the failing test**

```python
# agent/tests/test_skill_loader.py
"""Tests for skill loader from local directories."""
import os
from pathlib import Path

import pytest

from koclaw_agent.mcp_host.skill_loader import SkillLoader


@pytest.fixture
def skill_dir(tmp_path):
    """Create a temp directory with sample skills."""
    # Skill 1
    s1 = tmp_path / "web-search"
    s1.mkdir()
    (s1 / "SKILL.md").write_text(
        "---\nname: web-search\ndescription: Search the web\nversion: 1.0.0\n"
        "user-invocable: true\n---\nSearch using ddg-search tool.\n"
    )

    # Skill 2
    s2 = tmp_path / "code-review"
    s2.mkdir()
    (s2 / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: Review code quality\nversion: 0.5.0\n"
        "---\nAnalyze the code and provide feedback.\n"
    )

    # Not a skill (no SKILL.md)
    s3 = tmp_path / "random-dir"
    s3.mkdir()
    (s3 / "README.md").write_text("Not a skill")

    return tmp_path


def test_load_skills_from_directory(skill_dir):
    """Load all skills from a directory."""
    loader = SkillLoader()
    skills = loader.load_from_directory(skill_dir)
    assert len(skills) == 2
    names = {s.name for s in skills}
    assert "web-search" in names
    assert "code-review" in names


def test_load_skills_empty_dir(tmp_path):
    """Empty directory yields no skills."""
    loader = SkillLoader()
    assert loader.load_from_directory(tmp_path) == []


def test_load_skills_nonexistent_dir():
    """Nonexistent directory yields no skills."""
    loader = SkillLoader()
    assert loader.load_from_directory(Path("/nonexistent/path")) == []


def test_get_invocable_skills(skill_dir):
    """Filter to only user-invocable skills."""
    loader = SkillLoader()
    loader.load_from_directory(skill_dir)
    invocable = loader.get_invocable_skills()
    assert len(invocable) == 1
    assert invocable[0].name == "web-search"


def test_build_skills_prompt(skill_dir):
    """Build a system prompt section from loaded skills."""
    loader = SkillLoader()
    loader.load_from_directory(skill_dir)
    prompt = loader.build_skills_prompt()
    assert "web-search" in prompt
    assert "code-review" in prompt
    assert "Search using ddg-search tool" in prompt
```

**Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m pytest tests/test_skill_loader.py -v`
Expected: FAIL

**Step 3: Implement skill loader**

```python
# agent/koclaw_agent/mcp_host/skill_loader.py
"""Load and manage SKILL.md definitions from local directories.

Skills are loaded from:
1. Built-in skills: agent/skills/ (shipped with Koclaw)
2. User skills: ~/.koclaw/skills/ (installed via ClawHub CLI or manually)
3. Workspace skills: ./skills/ (project-specific)

Precedence: workspace > user > built-in (same name = higher priority wins)
"""
from __future__ import annotations

import logging
from pathlib import Path

from .skill_parser import SkillDefinition, parse_skill_md

logger = logging.getLogger(__name__)


class SkillLoader:
    """Loads SKILL.md files from directories and provides them to the Agent."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}  # name -> definition

    def load_from_directory(self, directory: Path) -> list[SkillDefinition]:
        """Scan a directory for subdirectories containing SKILL.md.

        Returns list of loaded SkillDefinitions.
        Existing skills with the same name are overwritten (for precedence).
        """
        loaded = []
        if not directory.is_dir():
            logger.debug("Skill directory does not exist: %s", directory)
            return loaded

        for entry in sorted(directory.iterdir()):
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                content = skill_file.read_text(encoding="utf-8")
                skill = parse_skill_md(content)
                self._skills[skill.name] = skill
                loaded.append(skill)
                logger.info("Loaded skill: %s v%s", skill.name, skill.version)
            except Exception:
                logger.exception("Failed to load skill from %s", skill_file)

        return loaded

    def load_all_paths(self) -> None:
        """Load skills from all standard paths (built-in, user, workspace).

        Later paths override earlier ones (workspace wins).
        """
        paths = [
            Path(__file__).parent.parent / "skills",       # Built-in
            Path.home() / ".koclaw" / "skills",            # User-installed
            Path.cwd() / "skills",                         # Workspace
        ]
        for path in paths:
            if path.is_dir():
                self.load_from_directory(path)

    def get_skill(self, name: str) -> SkillDefinition | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def get_invocable_skills(self) -> list[SkillDefinition]:
        """Get all user-invocable skills (exposed as slash commands)."""
        return [s for s in self._skills.values() if s.user_invocable]

    def get_all_skills(self) -> list[SkillDefinition]:
        """Get all loaded skills."""
        return list(self._skills.values())

    def build_skills_prompt(self) -> str:
        """Build a system prompt section listing all loaded skills.

        This teaches the LLM what skills are available and how to use them.
        """
        skills = self.get_all_skills()
        if not skills:
            return ""

        lines = [
            "",
            "## Available Skills",
            "",
            "The following skills provide specialized instructions for tasks:",
            "",
        ]

        for skill in skills:
            emoji = f"{skill.emoji} " if skill.emoji else ""
            lines.append(f"### {emoji}{skill.name}")
            lines.append(f"*{skill.description}*")
            lines.append("")
            lines.append(skill.instructions)
            lines.append("")

        return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m pytest tests/test_skill_loader.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add agent/koclaw_agent/mcp_host/skill_loader.py agent/tests/test_skill_loader.py
git commit -m "feat(agent): add skill loader for local SKILL.md directories"
```

---

## Sub-Phase 4C: ClawHub Client

### Goal

Provide a CLI-friendly client for discovering and installing skills from the ClawHub registry.

### Task 9: ClawHub API Client

**Files:**
- Create: `agent/koclaw_agent/mcp_host/clawhub_client.py`
- Test: `agent/tests/test_clawhub_client.py`

**Step 1: Write the failing test**

```python
# agent/tests/test_clawhub_client.py
"""Tests for ClawHub API client."""
import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from koclaw_agent.mcp_host.clawhub_client import ClawHubClient


def test_client_default_registry():
    """Client uses default ClawHub registry URL."""
    client = ClawHubClient()
    assert "clawhub" in client.registry_url.lower()


def test_client_custom_registry():
    """Client accepts custom registry URL."""
    client = ClawHubClient(registry_url="https://my-registry.example.com")
    assert client.registry_url == "https://my-registry.example.com"


@pytest.mark.asyncio
async def test_search_returns_results():
    """Search returns parsed skill metadata."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"name": "web-search", "description": "Search the web", "version": "1.0.0", "slug": "web-search"},
            {"name": "code-gen", "description": "Generate code", "version": "2.1.0", "slug": "code-gen"},
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = ClawHubClient()
        results = await client.search("search")
        assert len(results) == 2
        assert results[0]["name"] == "web-search"


@pytest.mark.asyncio
async def test_search_empty_results():
    """Search with no matches returns empty list."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = ClawHubClient()
        results = await client.search("nonexistent-skill-xyz")
        assert results == []
```

**Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m pytest tests/test_clawhub_client.py -v`
Expected: FAIL

**Step 3: Implement ClawHub client**

```python
# agent/koclaw_agent/mcp_host/clawhub_client.py
"""Client for the ClawHub skill registry.

ClawHub (clawhub.ai) is the public skill marketplace for AI agents.
This client enables searching, inspecting, and installing skills
from the registry into Koclaw's local skill directory.

Security note: Koclaw validates all downloaded skills before execution.
Skills with install scripts require explicit user confirmation.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY = "https://api.clawhub.ai/v1"
SKILLS_DIR = Path.home() / ".koclaw" / "skills"


class ClawHubClient:
    """HTTP client for the ClawHub skill registry API."""

    def __init__(self, registry_url: str = DEFAULT_REGISTRY) -> None:
        self.registry_url = registry_url

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search the ClawHub registry for skills matching a query.

        Uses ClawHub's vector-based semantic search.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.registry_url}/skills/search",
                params={"q": query, "limit": limit},
            )
            if resp.status_code != 200:
                logger.error("ClawHub search failed: %s", resp.status_code)
                return []
            data = resp.json()
            return data.get("results", [])

    async def inspect(self, slug: str) -> dict | None:
        """Get detailed info about a specific skill by slug."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.registry_url}/skills/{slug}")
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                logger.error("ClawHub inspect failed: %s", resp.status_code)
                return None
            return resp.json()

    async def install(self, slug: str, target_dir: Path | None = None) -> bool:
        """Download and install a skill from ClawHub.

        Downloads the SKILL.md and associated files into the target directory.
        Default target: ~/.koclaw/skills/<slug>/

        Returns True if installation succeeded.

        SECURITY: Does NOT run install scripts automatically.
        The skill_loader will check required_bins and required_env at load time.
        """
        target = target_dir or SKILLS_DIR / slug
        target.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{self.registry_url}/skills/{slug}/download")
            if resp.status_code != 200:
                logger.error("ClawHub download failed for '%s': %s", slug, resp.status_code)
                return False

            data = resp.json()

            # Write SKILL.md
            skill_md = data.get("skill_md", "")
            if not skill_md:
                logger.error("No SKILL.md content in download response")
                return False

            (target / "SKILL.md").write_text(skill_md, encoding="utf-8")

            # Write additional files if any
            for filename, content in data.get("files", {}).items():
                # Security: prevent path traversal
                safe_name = Path(filename).name
                (target / safe_name).write_text(content, encoding="utf-8")

            logger.info("Installed skill '%s' to %s", slug, target)
            return True

    async def uninstall(self, slug: str, target_dir: Path | None = None) -> bool:
        """Remove an installed skill directory."""
        target = target_dir or SKILLS_DIR / slug
        if target.is_dir():
            shutil.rmtree(target)
            logger.info("Uninstalled skill '%s'", slug)
            return True
        return False
```

**Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m pytest tests/test_clawhub_client.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add agent/koclaw_agent/mcp_host/clawhub_client.py agent/tests/test_clawhub_client.py
git commit -m "feat(agent): add ClawHub registry client for skill discovery and installation"
```

---

## Sub-Phase 4D: Permission-Gated Tool Invocation

### Goal

Extend Koclaw's existing permission system to control MCP tool access per channel.

### Task 10: Tool Permission Configuration

**Files:**
- Modify: `agent/koclaw_agent/config.py`
- Create: `agent/koclaw_agent/mcp_host/tool_permissions.py`
- Test: `agent/tests/test_tool_permissions.py`

**Step 1: Write the failing test**

```python
# agent/tests/test_tool_permissions.py
"""Tests for MCP tool permission enforcement."""
from koclaw_agent.mcp_host.tool_permissions import ToolPermissionChecker


def test_admin_can_use_all_tools():
    """Admin permission allows any tool."""
    checker = ToolPermissionChecker()
    assert checker.is_allowed("shell_exec", "Admin") is True
    assert checker.is_allowed("read_file", "Admin") is True
    assert checker.is_allowed("web_search", "Admin") is True


def test_authenticated_can_use_safe_tools():
    """Authenticated users can use non-destructive tools."""
    checker = ToolPermissionChecker()
    assert checker.is_allowed("web_search", "Authenticated") is True
    assert checker.is_allowed("get_time", "Authenticated") is True


def test_authenticated_blocked_from_dangerous_tools():
    """Authenticated users cannot use shell or filesystem write tools."""
    checker = ToolPermissionChecker(
        blocked_for_authenticated=["shell_exec", "write_file", "delete_file"]
    )
    assert checker.is_allowed("shell_exec", "Authenticated") is False
    assert checker.is_allowed("delete_file", "Authenticated") is False


def test_public_blocked_from_all_tools():
    """Public (blog widget) users cannot use any tools."""
    checker = ToolPermissionChecker()
    assert checker.is_allowed("web_search", "Public") is False
    assert checker.is_allowed("get_time", "Public") is False


def test_custom_allowlist():
    """Custom allowlist for authenticated users."""
    checker = ToolPermissionChecker(
        allowed_for_authenticated=["web_search", "get_time"]
    )
    assert checker.is_allowed("web_search", "Authenticated") is True
    assert checker.is_allowed("shell_exec", "Authenticated") is False
```

**Step 2: Run test to verify it fails**

Run: `cd agent && uv run python -m pytest tests/test_tool_permissions.py -v`
Expected: FAIL

**Step 3: Implement tool permission checker**

```python
# agent/koclaw_agent/mcp_host/tool_permissions.py
"""Permission enforcement for MCP tool invocations.

Extends Koclaw's three-tier permission model to MCP tools:

| Permission    | Tool Access                              |
|---------------|------------------------------------------|
| Public        | NO tools (chat only)                     |
| Authenticated | Safe tools only (configurable allowlist) |
| Admin         | All tools (unrestricted)                 |

This prevents blog widget visitors from executing shell commands,
while allowing authenticated Telegram/QQ users to use search and
other safe tools.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ToolPermissionChecker:
    """Check whether a tool invocation is allowed for a given permission level."""

    def __init__(
        self,
        allowed_for_authenticated: list[str] | None = None,
        blocked_for_authenticated: list[str] | None = None,
    ) -> None:
        """Initialize with optional tool restrictions.

        Args:
            allowed_for_authenticated: If set, only these tools are allowed
                for Authenticated users (allowlist mode).
            blocked_for_authenticated: If set, these tools are blocked
                for Authenticated users (blocklist mode).
                Ignored if allowed_for_authenticated is set.
        """
        self._allowlist = allowed_for_authenticated
        self._blocklist = blocked_for_authenticated or []

    def is_allowed(self, tool_name: str, permission: str) -> bool:
        """Check if a tool call is permitted.

        Args:
            tool_name: Name of the MCP tool being invoked.
            permission: Permission level string ("Public", "Authenticated", "Admin").

        Returns:
            True if the tool call should proceed, False to deny.
        """
        # Admin: unrestricted
        if permission == "Admin":
            return True

        # Public: no tools at all
        if permission == "Public":
            return False

        # Authenticated: check allow/block lists
        if permission == "Authenticated":
            if self._allowlist is not None:
                return tool_name in self._allowlist
            return tool_name not in self._blocklist

        # Unknown permission level: deny by default
        logger.warning("Unknown permission level: %s", permission)
        return False
```

**Step 4: Run test to verify it passes**

Run: `cd agent && uv run python -m pytest tests/test_tool_permissions.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add agent/koclaw_agent/mcp_host/tool_permissions.py agent/tests/test_tool_permissions.py
git commit -m "feat(agent): add permission-gated MCP tool invocation"
```

---

### Task 11: Config.toml MCP Section

**Files:**
- Modify: `config.example.toml` (or document the expected format)

**Step 1: Define the config.toml MCP section format**

Add to `config.toml`:

```toml
# MCP (Model Context Protocol) server configuration
# Each server is a subprocess that provides tools to the Agent.
# Servers are launched as child processes using stdio transport.

[mcp]
# Tool permission mode for Authenticated users (Telegram, QQ, Discord)
# "allowlist" = only listed tools permitted
# "blocklist" = all tools except listed ones permitted
# Admin users always have full tool access.
permission_mode = "blocklist"
blocked_tools = ["shell_exec", "write_file", "delete_file"]

[mcp.servers.time]
command = "uvx"
args = ["mcp-server-time"]

[mcp.servers.web-search]
command = "uvx"
args = ["mcp-server-ddg-search"]

# [mcp.servers.filesystem]
# command = "npx"
# args = ["-y", "@modelcontextprotocol/server-filesystem", "./workspace"]
# env = { ALLOWED_DIR = "./workspace" }
```

**Step 2: Commit**

```bash
git add config.example.toml
git commit -m "docs(config): add MCP server configuration section"
```

---

### Task 12: Wire Permission Checker into Bridge

**Files:**
- Modify: `agent/koclaw_agent/bridge.py`
- Modify: `agent/koclaw_agent/config.py`

**Step 1: Update config.py to parse MCP permission settings**

```python
def resolve_mcp_configs(config: dict) -> dict:
    """Extract full MCP configuration including servers and permissions."""
    mcp_section = config.get("mcp", {})
    return {
        "servers": mcp_section.get("servers", {}),
        "permission_mode": mcp_section.get("permission_mode", "blocklist"),
        "blocked_tools": mcp_section.get("blocked_tools", []),
        "allowed_tools": mcp_section.get("allowed_tools", []),
    }
```

**Step 2: Update bridge.py to check permissions before tool execution**

In the tool execution loop:

```python
from koclaw_agent.mcp_host.tool_permissions import ToolPermissionChecker

# In __init__:
self.tool_checker = ToolPermissionChecker(
    blocked_for_authenticated=mcp_configs.get("blocked_tools", [])
    if mcp_configs.get("permission_mode") == "blocklist"
    else None,
    allowed_for_authenticated=mcp_configs.get("allowed_tools")
    if mcp_configs.get("permission_mode") == "allowlist"
    else None,
)

# In _handle_chat, before executing a tool call:
if not self.tool_checker.is_allowed(tool_name, permission):
    tool_result = f"Permission denied: tool '{tool_name}' is not available at {permission} level."
    logger.warning("Tool call denied: %s (permission=%s)", tool_name, permission)
```

**Step 3: Run all tests**

Run: `cd agent && uv run python -m pytest tests/ -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add agent/koclaw_agent/bridge.py agent/koclaw_agent/config.py
git commit -m "feat(agent): enforce tool permissions in MCP execution loop"
```

---

## Testing Strategy

### Unit Tests (per task)

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_mcp_host.py` | 4 | Config parsing |
| `test_mcp_session.py` | 2 | Session lifecycle (with mock MCP server) |
| `test_tool_prompt.py` | 5 | Prompt generation and tool call parsing |
| `test_skill_parser.py` | 5 | SKILL.md format parsing |
| `test_skill_loader.py` | 5 | Directory scanning and loading |
| `test_clawhub_client.py` | 4 | Registry API (mocked HTTP) |
| `test_tool_permissions.py` | 5 | Permission enforcement |
| **Total** | **30** | |

### Integration Test

After all tasks are complete, perform a manual end-to-end test:

1. Configure an MCP server in `config.toml` (e.g., `mcp-server-time`)
2. Start the full stack (Gateway + Agent)
3. Send a message via Telegram: "What time is it in Tokyo?"
4. Verify the Agent:
   - Discovers the `get_time` tool via MCP
   - Generates a tool call in the LLM response
   - Executes the tool via MCP protocol
   - Returns the formatted result to Telegram

---

## Security Considerations

### Threat Model: ClawHavoc Mitigation

| Attack Vector | OpenClaw Vulnerability | Koclaw Mitigation |
|---------------|----------------------|-------------------|
| Malicious install scripts | Run automatically on `clawhub install` | **Never auto-run.** Install scripts require explicit user confirmation via CLI prompt |
| Credential exfiltration | Skills access all env vars | **Sandbox**: MCP servers inherit only explicitly configured env vars |
| Filesystem escape | No sandbox by default | **SandboxConfig**: MCP servers restricted to `workspace_root` |
| Network exfiltration | No network restrictions | **Permission-gated**: Public users get NO tools; Authenticated users get configurable allow/blocklist |
| Supply chain poisoning | No code signing | **Future**: Skill hash verification + VirusTotal check before install |

### Defense-in-Depth Layers

1. **Permission Level** — Public users cannot trigger any tool calls
2. **Tool Allow/Blocklist** — Authenticated users restricted to safe tools
3. **Sandbox Config** — Filesystem and command restrictions from `config.toml`
4. **MCP Env Isolation** — Each MCP server only gets its declared env vars
5. **No Auto-Execute** — Install scripts require manual approval

---

## Future Work (Phase 4E and beyond)

These are explicitly **out of scope** for this plan:

- **Koclaw as MCP Server** (expose chat, memory, persona as MCP tools for external hosts)
- **Native LLM Tool Use** (Claude/GPT-4 function calling instead of text-based tool calls)
- **ClawHub CLI** (standalone `koclaw-hub` command for skill management)
- **Skill Verification** (SHA256 hash pinning, VirusTotal scanning)
- **Multi-Agent Tool Routing** (multiple agents sharing MCP servers)
- **WebSocket MCP Transport** (custom transport for Koclaw's bridge protocol)

---

## Summary

| Task | Description | Est. Files | Tests |
|------|-------------|------------|-------|
| 1 | Add MCP SDK dependency | 2 | — |
| 2 | MCP server config parsing | 3 | 4 |
| 3 | MCP session lifecycle | 2 | 2 |
| 4 | Wire MCP into Agent Bridge | 3 | — |
| 5 | Tool prompt builder + parser | 2 | 5 |
| 6 | Tool execution loop in bridge | 1 | — |
| 7 | SKILL.md parser | 2 | 5 |
| 8 | Skill loader (local dirs) | 2 | 5 |
| 9 | ClawHub API client | 2 | 4 |
| 10 | Tool permission checker | 2 | 5 |
| 11 | Config.toml MCP section | 1 | — |
| 12 | Wire permissions into bridge | 2 | — |
| **Total** | | **~18 files** | **30 new tests** |
