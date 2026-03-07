"""OpenAI-compatible LLM provider.

Also works with DeepSeek, Ollama, and any OpenAI-compatible API
by passing a custom base_url.
"""

import json
import re
from typing import AsyncGenerator

from loguru import logger

from .base import BaseProvider, GenerateChunk, ToolCallRequest

DEFAULT_MODEL = "gpt-4o"

def _strip_internal_tags(text: str) -> str:
    """Remove thinking blocks, tool call blocks, and untagged thinking from LLM output.

    Handles:
    - Complete <think>...</think> blocks
    - Unclosed <think> (opening tag without close, or close without open)
    - Orphaned </think> anywhere in text
    - Same for <toolcall> / <tool_call> variants
    - Leading parenthetical thinking: (long analysis text...) at start
    """
    # 1. Complete tag blocks (non-greedy)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"<tool_?call>[\s\S]*?</tool_?call>", "", text)

    # 2. Unclosed opening tag to end of string
    text = re.sub(r"<think>[\s\S]*$", "", text)
    text = re.sub(r"<tool_?call>[\s\S]*$", "", text)

    # 3. Orphaned closing tag: content before it is leaked thinking
    #    (opening tag was consumed by streaming state machine in a prior chunk)
    text = re.sub(r"^[\s\S]*?</think>", "", text)
    text = re.sub(r"^[\s\S]*?</tool_?call>", "", text)
    # Any further orphaned close tags (shouldn't happen, but just in case)
    text = text.replace("</think>", "")
    text = text.replace("</toolcall>", "")
    text = text.replace("</tool_call>", "")

    # 4. Leading parenthetical thinking blocks: (long analysis...)
    #    Only strip at start, only if 20+ chars (avoid stripping normal parentheticals)
    text = re.sub(r"^(\s*\([^)]{20,}\)\s*)+", "", text)

    return text.strip()


def _mcp_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert MCP tool definitions to OpenAI function calling format.

    MCP format:
      {"name": "...", "description": "...", "inputSchema": {JSON Schema}}

    OpenAI format:
      {"type": "function", "function": {"name": "...", "description": "...",
       "parameters": {JSON Schema}}}
    """
    openai_tools = []
    for tool in tools:
        func_def: dict = {
            "name": tool["name"],
            "description": tool.get("description", ""),
        }
        schema = tool.get("inputSchema", {})
        if schema:
            func_def["parameters"] = schema
        else:
            func_def["parameters"] = {"type": "object", "properties": {}}

        openai_tools.append({"type": "function", "function": func_def})
    return openai_tools


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str | None = None, base_url: str | None = None,
                 extra_body: dict | None = None, defaults: dict | None = None,
                 supports_tools: bool = True):
        import openai

        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model or DEFAULT_MODEL
        self.extra_body = extra_body or {}
        self.defaults = defaults or {}
        self.supports_tools = supports_tools
        logger.info(f"OpenAI provider ready: model={self.model}, base_url={base_url or 'default'}")

    async def generate(
        self,
        text: str,
        session_id: str,
        attachments: list,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str | GenerateChunk, None]:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            for msg in history:
                role = msg["role"]
                if role == "tool":
                    # Native tool result: pass with tool_call_id
                    messages.append({
                        "role": "tool",
                        "tool_call_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    })
                elif role == "assistant" and "tool_calls" in msg:
                    # Assistant message that made a tool call
                    messages.append({
                        "role": "assistant",
                        "tool_calls": msg["tool_calls"],
                    })
                else:
                    messages.append({"role": role, "content": msg.get("content", "")})

        if attachments:
            content = []
            if text:
                content.append({"type": "text", "text": text})
            for att in attachments:
                if att.get("attachment_type") == "Image":
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": att["url"]},
                    })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": text})

        # Build API kwargs
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
        }
        # Apply provider-specific defaults (e.g. temperature, top_p, presence_penalty)
        for k, v in self.defaults.items():
            kwargs.setdefault(k, v)
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body

        # Use native function calling when tools are provided
        openai_tools = None
        if tools:
            openai_tools = _mcp_tools_to_openai(tools)
            kwargs["tools"] = openai_tools

        # Non-streaming when tools are provided (simpler tool call handling)
        if openai_tools:
            response = await self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message

            # Check for tool calls
            if message.tool_calls:
                tool_call = message.tool_calls[0]  # We only support one at a time
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                logger.info(
                    f"Native tool call: {tool_call.function.name}({arguments})"
                )
                yield GenerateChunk(
                    tool_call=ToolCallRequest(
                        name=tool_call.function.name,
                        arguments=arguments,
                        call_id=tool_call.id or "",
                    )
                )
            elif message.content:
                # LLM chose to respond with text instead of calling a tool
                cleaned = _strip_internal_tags(message.content)
                if cleaned:
                    yield cleaned
        else:
            # Streaming mode for regular chat (no tools)
            kwargs["stream"] = True
            stream = await self.client.chat.completions.create(**kwargs)

            _TAGS = [("<think>", "</think>"), ("<tool_call>", "</tool_call>"),
                     ("<toolcall>", "</toolcall>")]
            in_block = False
            async for chunk in stream:
                if not (chunk.choices and chunk.choices[0].delta.content):
                    continue
                content = chunk.choices[0].delta.content

                if in_block:
                    # Suppressing — only look for close tags
                    for _, close_tag in _TAGS:
                        if close_tag in content:
                            in_block = False
                            content = content.split(close_tag, 1)[1]
                            break
                    if in_block:
                        continue
                    if content:
                        yield content
                    continue

                # Not suppressing — check for open tags
                for open_tag, close_tag in _TAGS:
                    if open_tag in content:
                        before = content.split(open_tag, 1)[0]
                        if before:
                            yield before
                        # Check if close tag also in same chunk
                        after_open = content.split(open_tag, 1)[1]
                        if close_tag in after_open:
                            content = after_open.split(close_tag, 1)[1]
                        else:
                            in_block = True
                            content = ""
                        break

                if content:
                    yield content
