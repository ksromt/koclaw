"""Tests for MCP tool prompt generation."""
from koclaw_agent.mcp_host.tool_prompt import build_tool_prompt, parse_tool_call


def test_build_tool_prompt_single_tool():
    tools = [{"name": "get_time", "description": "Get the current time",
              "inputSchema": {"type": "object", "properties": {"timezone": {"type": "string"}}},
              "_mcp_server": "time"}]
    prompt = build_tool_prompt(tools)
    assert "get_time" in prompt
    assert "Get the current time" in prompt
    assert "timezone" in prompt


def test_build_tool_prompt_empty():
    assert build_tool_prompt([]) == ""


def test_parse_tool_call_valid():
    text = 'Let me check. {"tool": "get_time", "arguments": {"timezone": "UTC"}}'
    result = parse_tool_call(text)
    assert result is not None
    assert result["tool"] == "get_time"
    assert result["arguments"]["timezone"] == "UTC"


def test_parse_tool_call_no_call():
    assert parse_tool_call("Hello, how are you?") is None


def test_parse_tool_call_mcp_server_field():
    text = '{"mcp_server": "fs", "tool": "read_file", "arguments": {"path": "/tmp/a.txt"}}'
    result = parse_tool_call(text)
    assert result is not None
    assert result["tool"] == "read_file"
