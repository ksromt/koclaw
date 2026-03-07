"""Generate tool-calling prompts for LLMs and parse tool call responses."""
from __future__ import annotations

import json
import re

from loguru import logger


def build_tool_prompt(tools: list[dict]) -> str:
    """Build a compact tool-calling prompt for the system message."""
    if not tools:
        return ""

    lines = [
        "",
        "【ツール】",
        '使いたい時は {"tool": "名前", "arguments": {...}} だけを出力。',
        "ツール不要なら普通に返答。存在しないツールは使わないこと。",
        "",
    ]

    for tool in tools:
        name = tool["name"]
        desc = tool.get("description", "")
        short_desc = desc.split(".")[0] if desc else ""
        schema = tool.get("inputSchema", {})
        props = schema.get("properties", {})
        required = set(schema.get("required", []))

        lines.append(f"- {name}: {short_desc}")
        for pname, pinfo in props.items():
            ptype = pinfo.get("type", "")
            pdesc = pinfo.get("description", "")
            pdesc = pdesc.split(".")[0] if pdesc else ""
            req_mark = " *必須*" if pname in required else ""
            lines.append(f"    {pname} ({ptype}{req_mark}): {pdesc}")

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
