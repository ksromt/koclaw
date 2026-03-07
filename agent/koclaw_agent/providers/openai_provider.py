"""OpenAI-compatible LLM provider.

Also works with DeepSeek, Ollama, and any OpenAI-compatible API
by passing a custom base_url.
"""

import json
from typing import AsyncGenerator

from loguru import logger

from .base import BaseProvider, GenerateChunk, ToolCallRequest

DEFAULT_MODEL = "gpt-4o"


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
                 extra_body: dict | None = None, defaults: dict | None = None):
        import openai

        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model or DEFAULT_MODEL
        self.extra_body = extra_body or {}
        self.defaults = defaults or {}
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
                yield message.content
        else:
            # Streaming mode for regular chat (no tools)
            kwargs["stream"] = True
            stream = await self.client.chat.completions.create(**kwargs)

            in_think = False
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    # Strip thinking blocks (e.g. Qwen3.5 <think>...</think>)
                    if "<think>" in content:
                        in_think = True
                        content = content.split("<think>")[0]
                    if "</think>" in content:
                        in_think = False
                        content = content.split("</think>", 1)[1]
                    if in_think:
                        continue
                    if content:
                        yield content
