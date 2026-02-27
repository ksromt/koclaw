"""GPT-SoVITS TTS provider.

Calls the GPT-SoVITS API server (typically at http://127.0.0.1:9880).
Reference: AIKokoron's gpt_sovits_tts.py
"""

import httpx
from loguru import logger

from .base_tts import BaseTTS


class GPTSoVITSTTS(BaseTTS):
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9880",
        refer_wav_path: str = "",
        prompt_text: str = "",
        prompt_language: str = "en",
        text_language: str = "auto",
    ):
        self.base_url = base_url.rstrip("/")
        self.refer_wav_path = refer_wav_path
        self.prompt_text = prompt_text
        self.prompt_language = prompt_language
        self.text_language = text_language
        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"GPT-SoVITS TTS initialized: {self.base_url}")

    async def synthesize(self, text: str, language: str = "auto") -> bytes:
        params: dict[str, str] = {
            "text": text,
            "text_language": language if language != "auto" else self.text_language,
        }
        if self.refer_wav_path:
            params["refer_wav_path"] = self.refer_wav_path
            params["prompt_text"] = self.prompt_text
            params["prompt_language"] = self.prompt_language

        response = await self.client.get(f"{self.base_url}/tts", params=params)
        response.raise_for_status()
        return response.content

    def is_available(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/", timeout=3.0)
            return resp.status_code < 500
        except Exception:
            return False
