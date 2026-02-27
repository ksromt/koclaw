"""Anthropic (Claude) LLM provider.

Reference: AIKokoron's implementation at
D:\\personal_development\\AI_assistant\\AIKokoron\\src\\open_llm_vtuber\\agent\\stateless_llm\\
"""

import os
from typing import AsyncGenerator

from loguru import logger

from .base import BaseProvider

DEFAULT_MODEL = "claude-sonnet-4-20250514"
SYSTEM_PROMPT = (
    "You are Kokoron, a helpful and friendly AI assistant. "
    "Respond naturally and concisely. You can communicate in "
    "English, Japanese, and Chinese."
)


class AnthropicProvider(BaseProvider):
    def __init__(self):
        import anthropic

        self.client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
        self.model = os.environ.get("KOCLAW_ANTHROPIC_MODEL", DEFAULT_MODEL)
        logger.info(f"Anthropic provider ready: model={self.model}")

    async def generate(
        self,
        text: str,
        session_id: str,
        attachments: list,
    ) -> AsyncGenerator[str, None]:
        # Build messages
        messages = [{"role": "user", "content": text}]

        # TODO: Add attachment handling for multimodal (images)
        # TODO: Add conversation history from memory system

        async with self.client.messages.stream(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
