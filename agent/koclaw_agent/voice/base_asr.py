from abc import ABC, abstractmethod


class BaseASR(ABC):
    @abstractmethod
    async def transcribe(self, audio_data: bytes, language: str = "auto") -> str:
        """Transcribe audio bytes to text."""
        ...
