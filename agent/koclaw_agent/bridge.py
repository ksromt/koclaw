"""
WebSocket bridge server — receives requests from Koclaw Gateway,
routes to LLM, and streams responses back.

Protocol:
  Gateway -> Agent: {"type": "chat", "session_id": "...", "text": "...", ...}
  Agent -> Gateway: {"type": "text_chunk", "session_id": "...", "content": "..."}
  Agent -> Gateway: {"type": "done", "session_id": "..."}
"""

import asyncio
import base64
import json

import websockets
from loguru import logger

from .expression import extract_expressions
from .llm_router import LLMRouter
from .memory import FileMemory
from .persona import Persona


class AgentBridge:
    """WebSocket server that bridges Gateway requests to LLM responses."""

    def __init__(self, host: str = "127.0.0.1", port: int = 18790):
        self.host = host
        self.port = port
        self.llm_router = LLMRouter()
        self.memory = FileMemory()
        self.persona = Persona.from_yaml_file()
        self.tts = self._init_tts()
        self.asr = self._init_asr()

    def _init_tts(self):
        """Initialize TTS from persona voice config, if available."""
        voice_config = self.persona.voice
        if voice_config.get("tts_provider") == "gpt_sovits":
            try:
                from .voice import GPTSoVITSTTS

                sovits_cfg = voice_config.get("gpt_sovits", {})
                return GPTSoVITSTTS(
                    base_url=sovits_cfg.get("base_url", "http://127.0.0.1:9880"),
                    refer_wav_path=sovits_cfg.get("refer_wav_path", ""),
                    prompt_text=sovits_cfg.get("prompt_text", ""),
                    prompt_language=sovits_cfg.get("prompt_language", "en"),
                    text_language=sovits_cfg.get("text_language", "auto"),
                )
            except ImportError:
                logger.warning("httpx not installed, TTS disabled")
        return None

    def _init_asr(self):
        """Initialize ASR from persona voice config, if available."""
        voice_config = self.persona.voice
        if voice_config.get("asr_provider") == "faster_whisper":
            try:
                from .voice import FasterWhisperASR

                whisper_cfg = voice_config.get("faster_whisper", {})
                return FasterWhisperASR(
                    model_size=whisper_cfg.get("model_size", "base"),
                    language=whisper_cfg.get("language", "auto"),
                )
            except ImportError:
                logger.warning("faster-whisper not installed, ASR disabled")
        return None

    async def handle_connection(self, websocket: websockets.WebSocketServerProtocol):
        """Handle a single Gateway connection."""
        logger.info("Gateway connected")

        try:
            async for raw_message in websocket:
                try:
                    message = json.loads(raw_message)
                    msg_type = message.get("type", "")

                    if msg_type == "chat":
                        await self._handle_chat(websocket, message)
                    elif msg_type == "audio_input":
                        await self._handle_audio_input(websocket, message)
                    elif msg_type == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                    else:
                        logger.warning(f"Unknown message type: {msg_type}")

                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {raw_message[:200]}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "session_id": message.get("session_id", ""),
                        "content": str(e),
                    }))

        except websockets.exceptions.ConnectionClosed:
            logger.info("Gateway disconnected")

    async def _handle_chat(self, websocket, message: dict):
        """Process a chat request and stream response chunks."""
        session_id = message.get("session_id", "")
        text = message.get("text", "")
        permission = message.get("permission", "Public")
        channel = message.get("channel", "telegram")
        system_prompt = message.get("system_prompt") or self.persona.system_prompt(channel)

        logger.info(
            f"Chat request: session={session_id}, "
            f"channel={channel}, permission={permission}"
        )

        # Load conversation history for context
        history = await self.memory.get_history(session_id)

        # Persist the user message
        if text:
            await self.memory.add_message(session_id, "user", text)

        # Stream LLM response
        full_response = ""
        async for chunk in self.llm_router.generate(
            text=text,
            session_id=session_id,
            permission=permission,
            attachments=message.get("attachments", []),
            system_prompt=system_prompt,
            history=history,
        ):
            full_response += chunk
            await websocket.send(json.dumps({
                "type": "text_chunk",
                "session_id": session_id,
                "content": chunk,
            }))

        # Persist the assistant response
        if full_response:
            await self.memory.add_message(session_id, "assistant", full_response)

        # Extract expressions for Live2D animation
        expr_result = extract_expressions(full_response)

        # Signal completion (include expressions for frontend)
        await websocket.send(json.dumps({
            "type": "done",
            "session_id": session_id,
            "expressions": expr_result.expressions,
        }))

        # Optional: synthesize audio for clients that request it
        want_audio = message.get("audio_response", False)
        if want_audio and self.tts and full_response:
            try:
                audio_data = await self.tts.synthesize(expr_result.clean_text)
                await websocket.send(json.dumps({
                    "type": "audio",
                    "session_id": session_id,
                    "format": "wav",
                    "data": base64.b64encode(audio_data).decode("ascii"),
                }))
            except Exception as e:
                logger.error(f"TTS synthesis failed: {e}")

    async def _handle_audio_input(self, websocket, message: dict):
        """Transcribe audio input and process as chat."""
        session_id = message.get("session_id", "")

        if not self.asr:
            await websocket.send(json.dumps({
                "type": "error",
                "session_id": session_id,
                "content": "ASR not configured",
            }))
            return

        audio_data = base64.b64decode(message.get("audio_data", ""))

        # Transcribe
        text = await self.asr.transcribe(audio_data)
        logger.info(f"ASR transcription: {text[:100]}")

        # Send transcription to client
        await websocket.send(json.dumps({
            "type": "transcription",
            "session_id": session_id,
            "content": text,
        }))

        # Process as regular chat with audio response enabled
        chat_msg = {**message, "type": "chat", "text": text, "audio_response": True}
        await self._handle_chat(websocket, chat_msg)

    async def start(self):
        """Start the WebSocket bridge server."""
        logger.info(f"Agent bridge starting on ws://{self.host}:{self.port}")

        async with websockets.serve(
            self.handle_connection,
            self.host,
            self.port,
        ):
            logger.info("Agent bridge ready")
            await asyncio.Future()  # Run forever
