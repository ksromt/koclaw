"""Tests for MCP tool prompt generation and output sanitization."""
from koclaw_agent.mcp_host.tool_prompt import build_tool_prompt, parse_tool_call
from koclaw_agent.providers.openai_provider import _strip_internal_tags


def test_build_tool_prompt_single_tool():
    tools = [{"name": "get_time", "description": "Get the current time.",
              "inputSchema": {"type": "object",
                              "properties": {"timezone": {"type": "string"}},
                              "required": ["timezone"]},
              "_mcp_server": "time"}]
    prompt = build_tool_prompt(tools)
    assert "get_time(timezone)" in prompt
    assert "Get the current time" in prompt


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


# --- _strip_internal_tags tests ---

def test_strip_complete_think_block():
    text = "<think>用户重启后发消息来</think>こんにちは先生！"
    assert _strip_internal_tags(text) == "こんにちは先生！"


def test_strip_unclosed_think_tag():
    text = "<think>The user set up a reminder 30 seconds ago..."
    assert _strip_internal_tags(text) == ""


def test_strip_orphaned_close_think():
    """Content before orphaned </think> is leaked thinking — strip it all."""
    text = "some leftover thinking content</think>こんにちは！"
    assert _strip_internal_tags(text) == "こんにちは！"


def test_strip_orphaned_close_think_only():
    """Orphaned </think> at very start — common in scheduler path."""
    text = "</think>\nHere is your reminder!"
    assert _strip_internal_tags(text) == "Here is your reminder!"


def test_strip_leading_parenthetical_thinking_jp():
    text = "(先生が日本語で話しかけてきた...私の判断が正しいか...)\nこんにちは先生！"
    result = _strip_internal_tags(text)
    assert "先生が日本語" not in result
    assert "こんにちは先生！" in result


def test_strip_multiple_parenthetical_blocks():
    text = "(analysis block one is long enough)\n(analysis block two also long enough)\nActual response"
    result = _strip_internal_tags(text)
    assert "analysis" not in result
    assert "Actual response" in result


def test_preserve_short_parenthetical():
    """Short parentheticals like (笑) should NOT be stripped."""
    text = "(笑) そうですね"
    assert _strip_internal_tags(text) == "(笑) そうですね"


def test_strip_think_with_residual_content():
    """English thinking with </think> residual — scheduler pattern."""
    text = "The user set up a reminder 30 seconds ago. Let me compose a message.</think>\nHey! Your reminder fired!"
    result = _strip_internal_tags(text)
    assert "reminder 30 seconds" not in result
    assert "</think>" not in result
    assert "Hey! Your reminder fired!" in result


def test_strip_toolcall_tags():
    text = "<toolcall>some tool json</toolcall>response text"
    assert _strip_internal_tags(text) == "response text"


def test_clean_text_passes_through():
    text = "こんにちは先生！今日もいい天気ですね。"
    assert _strip_internal_tags(text) == text
