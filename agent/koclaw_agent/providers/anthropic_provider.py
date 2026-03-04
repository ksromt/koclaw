"""Anthropic (Claude) LLM provider."""

from typing import AsyncGenerator

from loguru import logger

from .base import BaseProvider

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str, model: str | None = None):
        import anthropic

        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model or DEFAULT_MODEL
        logger.info(f"Anthropic provider ready: model={self.model}")

    async def generate(
        self,
        text: str,
        session_id: str,
        attachments: list,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        messages = []

        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

        if attachments:
            content = []
            for att in attachments:
                if att.get("attachment_type") == "Image":
                    content.append({
                        "type": "image",
                        "source": {"type": "url", "url": att["url"]},
                    })
            if text:
                content.append({"type": "text", "text": text})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": text})


        async with self.client.messages.stream(
            model=self.model,
            max_tokens=4096,
            system=system_prompt or "",
            messages=messages,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
