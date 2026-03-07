"""
LLM Router — routes chat requests to the appropriate LLM provider.

Supports: Anthropic (Claude), OpenAI, DeepSeek, Ollama (local).
Provider selection is config-driven via config.toml.
"""

from typing import AsyncGenerator

from loguru import logger


class LLMRouter:
    """Routes requests to the configured LLM provider and streams responses."""

    def __init__(self, provider_configs: dict | None = None):
        self._providers: dict[str, object] = {}
        self._configs = provider_configs or {}
        self.default_provider = self._configs.get("_default", "anthropic")
        self._init_providers()

    def _init_providers(self):
        """Initialize available providers based on resolved config."""
        # OpenAI
        openai_cfg = self._configs.get("openai", {})
        if openai_cfg.get("api_key"):
            try:
                from .providers.openai_provider import OpenAIProvider

                self._providers["openai"] = OpenAIProvider(
                    api_key=openai_cfg["api_key"],
                    model=openai_cfg.get("model"),
                    base_url=openai_cfg.get("base_url"),
                )
                logger.info("OpenAI provider initialized")
            except ImportError:
                logger.warning("openai package not installed")

        # Anthropic
        anthropic_cfg = self._configs.get("anthropic", {})
        if anthropic_cfg.get("api_key"):
            try:
                from .providers.anthropic_provider import AnthropicProvider

                self._providers["anthropic"] = AnthropicProvider(
                    api_key=anthropic_cfg["api_key"],
                    model=anthropic_cfg.get("model"),
                )
                logger.info("Anthropic provider initialized")
            except ImportError:
                logger.warning("anthropic package not installed")

        # DeepSeek (OpenAI-compatible)
        deepseek_cfg = self._configs.get("deepseek", {})
        if deepseek_cfg.get("api_key"):
            try:
                from .providers.openai_provider import OpenAIProvider

                self._providers["deepseek"] = OpenAIProvider(
                    api_key=deepseek_cfg["api_key"],
                    model=deepseek_cfg.get("model", "deepseek-chat"),
                    base_url=deepseek_cfg.get("base_url", "https://api.deepseek.com/v1"),
                )
                logger.info("DeepSeek provider initialized")
            except ImportError:
                logger.warning("openai package not installed")

        # Kokoron (local fine-tuned model, OpenAI-compatible API)
        kokoron_cfg = self._configs.get("kokoron", {})
        if kokoron_cfg.get("base_url"):
            try:
                from .providers.openai_provider import OpenAIProvider

                self._providers["kokoron"] = OpenAIProvider(
                    api_key=kokoron_cfg.get("api_key", "not-needed"),
                    model=kokoron_cfg.get("model", "kokoron"),
                    base_url=kokoron_cfg["base_url"],
                    extra_body={"chat_template_kwargs": {"enable_thinking": True}},
                    defaults={"temperature": 0.9, "top_p": 0.9, "presence_penalty": 0.5},
                    supports_tools=False,
                )
                logger.info("Kokoron provider initialized (local fine-tuned model)")
            except ImportError:
                logger.warning("openai package not installed, Kokoron provider unavailable")

        if not self._providers:
            logger.warning("No LLM providers configured. Using echo mode.")

    def supports_native_tools(self, provider: str | None = None) -> bool:
        """Check if the active provider supports native function calling."""
        name = provider or self.default_provider
        p = self._providers.get(name)
        return getattr(p, "supports_tools", True)

    async def generate(
        self,
        text: str,
        session_id: str,
        permission: str = "Authenticated",
        attachments: list = None,
        provider: str = None,
        system_prompt: str = None,
        history: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator:
        """Generate a response from the LLM.

        Yields str (text chunks) or GenerateChunk (when native tool calling
        is used and the LLM requests a tool call).
        """
        provider_name = provider or self.default_provider

        if provider_name in self._providers:
            provider_instance = self._providers[provider_name]
            async for chunk in provider_instance.generate(
                text,
                session_id,
                attachments or [],
                system_prompt=system_prompt,
                history=history,
                tools=tools,
            ):
                yield chunk
        else:
            logger.debug(f"Echo mode: {text}")
            yield f"[Echo] {text}"
            yield "\n\n(No LLM provider configured for '{provider_name}')"
