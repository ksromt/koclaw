"""Faster-Whisper ASR provider.

Uses faster-whisper for local speech recognition.
Reference: AIKokoron's faster_whisper_asr.py
"""

from __future__ import annotations

import asyncio
import io

from loguru import logger

from .base_asr import BaseASR


class FasterWhisperASR(BaseASR):
    def __init__(self, model_size: str = "base", language: str = "auto"):
        self.model_size = model_size
        self.language = language if language != "auto" else None
        self._model = None
        logger.info(f"FasterWhisper ASR initialized: model={model_size}, lang={language}")

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, compute_type="int8")
        return self._model

    async def transcribe(self, audio_data: bytes, language: str = "auto") -> str:
        lang = language if language != "auto" else self.language
        model = self._get_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._transcribe_sync, model, audio_data, lang
        )

    def _transcribe_sync(self, model, audio_data: bytes, language: str | None) -> str:
        audio_file = io.BytesIO(audio_data)
        segments, _info = model.transcribe(
            audio_file,
            language=language,
            beam_size=5,
        )
        return " ".join(seg.text.strip() for seg in segments)
