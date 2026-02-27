"""Abstract base for conversation memory backends."""

from abc import ABC, abstractmethod


class BaseMemory(ABC):
    """Abstract base for conversation memory backends.

    To add a new backend:
    1. Create a new file in this directory (e.g., redis_memory.py)
    2. Implement this interface
    3. Register it in bridge.py or via config
    """

    @abstractmethod
    async def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get conversation history for a session.

        Returns list of {"role": ..., "content": ...}.
        """
        ...

    @abstractmethod
    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        ...

    @abstractmethod
    async def clear_history(self, session_id: str) -> None:
        """Clear conversation history for a session."""
        ...

    @abstractmethod
    async def list_sessions(self) -> list[str]:
        """List all known session IDs."""
        ...
