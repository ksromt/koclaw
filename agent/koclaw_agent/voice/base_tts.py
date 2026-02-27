from abc import ABC, abstractmethod


class BaseTTS(ABC):
    @abstractmethod
    async def synthesize(self, text: str, language: str = "auto") -> bytes:
        """Convert text to audio bytes (WAV format)."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if TTS backend is accessible."""
        ...
