"""OpenAI-compatible LLM provider.

Also works with DeepSeek, Ollama, and any OpenAI-compatible API
by passing a custom base_url.
"""

from typing import AsyncGenerator

from loguru import logger

from .base import BaseProvider

DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str | None = None, base_url: str | None = None):
        import openai

        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model or DEFAULT_MODEL
        logger.info(f"OpenAI provider ready: model={self.model}, base_url={base_url or 'default'}")

    async def generate(
        self,
        text: str,
        session_id: str,
        attachments: list,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": text})

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=4096,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
