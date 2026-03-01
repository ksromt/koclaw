"""Base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator


@dataclass
class ToolCallRequest:
    """Structured tool call request from the LLM (native function calling)."""

    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class GenerateChunk:
    """A chunk of LLM generation output.

    Either text content (streaming) or a tool call request (native FC).
    At most one of `text` or `tool_call` is set per chunk.
    """

    text: str | None = None
    tool_call: ToolCallRequest | None = None


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
        system_prompt: str | None = None,
        history: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str | GenerateChunk, None]:
        """Generate a streaming response.

        Yields str (text chunks) for backward compatibility.
        When `tools` is provided and the LLM decides to call a tool,
        yields a GenerateChunk with `tool_call` set.
        """
        ...
