"""Generate tool-calling prompts for LLMs and parse tool call responses."""
from __future__ import annotations

import json
import re

from loguru import logger


def build_tool_prompt(tools: list[dict]) -> str:
    """Build a system prompt section describing available MCP tools."""
    if not tools:
        return ""

    lines = [
        "", "## Available Tools", "",
        "You have access to the following tools via MCP (Model Context Protocol).",
        "To use a tool, output ONLY a JSON object (nothing else):", "",
        "```json", '{"tool": "<tool_name>", "arguments": {<arguments>}}', "```", "",
        "Rules:",
        "- Output ONLY the JSON object when calling a tool — no other text.",
        "- Only use ONE tool call per response.",
        "- Do not invent tools that are not listed below.",
        "- If no tool is needed, respond normally without JSON.",
        "- IMPORTANT: ALWAYS call a tool instead of saying you cannot do something.",
        "- Do NOT ask the user for parameters that have reasonable defaults.",
        "  For example, if the user asks 'what time is it?', immediately call "
        "get_current_time with the user's timezone from the Environment section.",
        "- When in doubt, call the tool with a sensible default rather than asking.", "",
        "### Tool List", "",
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


def _extract_top_level_braces(text: str) -> list[str]:
    """Extract all top-level brace-balanced substrings from text."""
    results = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                results.append(text[start:i + 1])
                start = -1
    return results


def parse_tool_call(text: str) -> dict | None:
    """Extract a JSON tool call from LLM output text."""
    # First try fenced code blocks
    fenced = re.findall(r"```json\s*\n?(.*?)\n?```", text, re.DOTALL)
    for match in fenced:
        try:
            obj = json.loads(match.strip())
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    # Then try brace-balanced extraction
    for candidate in _extract_top_level_braces(text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    return None
