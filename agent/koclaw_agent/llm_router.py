"""
LLM Router — routes chat requests to the appropriate LLM provider.

Supports: Anthropic (Claude), OpenAI, DeepSeek, Ollama (local).
Provider selection is config-driven; adding a new provider requires only
implementing the generate() async generator pattern.

NOTE: AIKokoron already has LLM implementations at:
  D:\\personal_development\\AI_assistant\\AIKokoron\\src\\open_llm_vtuber\\agent\\stateless_llm\\
These can be adapted when integrating the full pipeline in Phase 2.
"""

import os
from typing import AsyncGenerator

from loguru import logger


class LLMRouter:
    """Routes requests to the configured LLM provider and streams responses."""

    def __init__(self):
        self.default_provider = os.environ.get("KOCLAW_DEFAULT_PROVIDER", "anthropic")
        self._providers: dict[str, object] = {}
        self._init_providers()

    def _init_providers(self):
        """Initialize available providers based on environment variables."""
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                from .providers.anthropic_provider import AnthropicProvider
                self._providers["anthropic"] = AnthropicProvider()
                logger.info("Anthropic provider initialized")
            except ImportError:
                logger.warning("anthropic package not installed")

        if os.environ.get("OPENAI_API_KEY"):
            try:
                from .providers.openai_provider import OpenAIProvider
                self._providers["openai"] = OpenAIProvider()
                logger.info("OpenAI provider initialized")
            except ImportError:
                logger.warning("openai package not installed")

        if not self._providers:
            logger.warning("No LLM providers configured. Using echo mode.")

    async def generate(
        self,
        text: str,
        session_id: str,
        permission: str = "Authenticated",
        attachments: list = None,
        provider: str = None,
        system_prompt: str = None,
        history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Generate a response from the LLM, yielding text chunks."""
        provider_name = provider or self.default_provider

        if provider_name in self._providers:
            provider_instance = self._providers[provider_name]
            async for chunk in provider_instance.generate(
                text,
                session_id,
                attachments or [],
                system_prompt=system_prompt,
                history=history,
            ):
                yield chunk
        else:
            # Echo mode — useful for testing without API keys
            logger.debug(f"Echo mode: {text}")
            yield f"[Echo] {text}"
            yield "\n\n(No LLM provider configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY)"
