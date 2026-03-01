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
from .mcp_host.server_manager import McpServerManager
from .mcp_host.tool_permissions import ToolPermissionChecker
from .mcp_host.tool_prompt import build_tool_prompt, parse_tool_call
from .memory import FileMemory
from .persona import Persona


class AgentBridge:
    """WebSocket server that bridges Gateway requests to LLM responses."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18790,
        provider_configs: dict | None = None,
        mcp_configs: dict | None = None,
    ):
        self.host = host
        self.port = port
        self.llm_router = LLMRouter(provider_configs)
        self.memory = FileMemory()
        self.persona = Persona.from_yaml_file()
        self.tts = self._init_tts()
        self.asr = self._init_asr()

        # MCP tool server management
        self.mcp_manager = McpServerManager()
        mcp_configs = mcp_configs or {}
        if mcp_configs.get("servers"):
            self.mcp_manager.load_configs(mcp_configs["servers"])

        # Tool permission enforcement
        perm_mode = mcp_configs.get("permission_mode", "blocklist")
        self.tool_checker = ToolPermissionChecker(
            allowed_for_authenticated=(
                mcp_configs.get("allowed_tools") if perm_mode == "allowlist" else None
            ),
            blocked_for_authenticated=(
                mcp_configs.get("blocked_tools", []) if perm_mode == "blocklist" else None
            ),
        )

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
        """Process a chat request, execute MCP tools if needed, stream response."""
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

        # Build MCP tool prompt if tools available and permission allows
        tool_prompt_section = ""
        if permission != "Public" and self.mcp_manager.configs:
            tools = await self.mcp_manager.list_all_tools()
            if tools:
                tool_prompt_section = build_tool_prompt(tools)

        full_system = system_prompt + tool_prompt_section

        # LLM generation with tool execution loop (max 3 iterations)
        full_response = ""
        current_text = text
        current_attachments = message.get("attachments", [])

        for iteration in range(3):
            iteration_response = ""
            async for chunk in self.llm_router.generate(
                text=current_text,
                session_id=session_id,
                permission=permission,
                attachments=current_attachments,
                system_prompt=full_system,
                history=history,
            ):
                iteration_response += chunk
                await websocket.send(json.dumps({
                    "type": "text_chunk",
                    "session_id": session_id,
                    "content": chunk,
                }))

            full_response += iteration_response

            # Check for tool call in this iteration's response
            tool_call = parse_tool_call(iteration_response)
            if tool_call is None:
                break  # No tool call, generation is complete

            tool_name = tool_call.get("tool", "")
            tool_args = tool_call.get("arguments", {})

            # Permission check before executing
            if not self.tool_checker.is_allowed(tool_name, permission):
                deny_msg = f"\n[Tool '{tool_name}' denied for {permission} permission level]\n"
                await websocket.send(json.dumps({
                    "type": "text_chunk",
                    "session_id": session_id,
                    "content": deny_msg,
                }))
                full_response += deny_msg
                break

            # Execute MCP tool
            logger.info(f"Executing MCP tool: {tool_name}({tool_args})")
            try:
                tool_result = await self.mcp_manager.call_tool(tool_name, tool_args)
            except Exception as e:
                logger.error(f"MCP tool execution failed: {tool_name}: {e}")
                tool_result = f"Error: Tool '{tool_name}' execution failed: {e}"
            logger.info(f"Tool result: {tool_result[:200]}")

            # Feed tool result back as next iteration's input
            history.append({"role": "assistant", "content": iteration_response})
            history.append({
                "role": "user",
                "content": f"[Tool Result: {tool_name}]\n{tool_result}",
            })
            current_text = f"[Tool Result: {tool_name}]\n{tool_result}"
            current_attachments = []  # No attachments on tool result iterations

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

        # Connect to MCP servers before accepting gateway connections
        if self.mcp_manager.configs:
            logger.info(f"Connecting to {len(self.mcp_manager.configs)} MCP server(s)...")
            await self.mcp_manager.connect_all()
            tools = await self.mcp_manager.list_all_tools()
            logger.info(f"MCP ready: {len(tools)} tool(s) available")

        try:
            async with websockets.serve(
                self.handle_connection,
                self.host,
                self.port,
            ):
                logger.info("Agent bridge ready")
                await asyncio.Future()  # Run forever
        finally:
            await self.mcp_manager.shutdown()
