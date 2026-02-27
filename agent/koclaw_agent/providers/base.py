"""Base class for LLM providers."""

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class BaseProvider(ABC):
    """Abstract base for all LLM providers.

    To add a new provider:
    1. Create a new file in this directory (e.g., deepseek_provider.py)
    2. Implement this interface
    3. Register it in llm_router.py's _init_providers()
    """

    @abstractmethod
    async def generate(
        self,
        text: str,
        session_id: str,
        attachments: list,
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming response. Yield text chunks."""
        ...
