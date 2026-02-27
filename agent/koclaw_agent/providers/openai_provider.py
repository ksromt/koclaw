"""OpenAI-compatible LLM provider.

Also works with DeepSeek, Ollama, and any OpenAI-compatible API
by setting OPENAI_BASE_URL.
"""

import os
from typing import AsyncGenerator

from loguru import logger

from .base import BaseProvider

DEFAULT_MODEL = "gpt-4o"
DEFAULT_SYSTEM_PROMPT = (
    "You are Kokoron, a helpful and friendly AI assistant. "
    "Respond naturally and concisely. You can communicate in "
    "English, Japanese, and Chinese."
)


class OpenAIProvider(BaseProvider):
    def __init__(self):
        import openai

        self.client = openai.AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
        self.model = os.environ.get("KOCLAW_OPENAI_MODEL", DEFAULT_MODEL)
        logger.info(f"OpenAI provider ready: model={self.model}")

    async def generate(
        self,
        text: str,
        session_id: str,
        attachments: list,
        system_prompt: str | None = None,
    ) -> AsyncGenerator[str, None]:
        messages = [
            {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=4096,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
