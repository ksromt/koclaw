"""
WebSocket bridge server — receives requests from Koclaw Gateway,
routes to LLM, and streams responses back.

Protocol:
  Gateway -> Agent: {"type": "chat", "session_id": "...", "text": "...", ...}
  Agent -> Gateway: {"type": "text_chunk", "session_id": "...", "content": "..."}
  Agent -> Gateway: {"type": "done", "session_id": "..."}
"""

import asyncio
import json
from typing import AsyncGenerator

import websockets
from loguru import logger

from .llm_router import LLMRouter


class AgentBridge:
    """WebSocket server that bridges Gateway requests to LLM responses."""

    def __init__(self, host: str = "127.0.0.1", port: int = 18790):
        self.host = host
        self.port = port
        self.llm_router = LLMRouter()

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
        system_prompt = message.get("system_prompt")

        logger.info(
            f"Chat request: session={session_id}, "
            f"channel={message.get('channel')}, "
            f"permission={permission}"
        )

        # Stream LLM response
        async for chunk in self.llm_router.generate(
            text=text,
            session_id=session_id,
            permission=permission,
            attachments=message.get("attachments", []),
            system_prompt=system_prompt,
        ):
            await websocket.send(json.dumps({
                "type": "text_chunk",
                "session_id": session_id,
                "content": chunk,
            }))

        # Signal completion
        await websocket.send(json.dumps({
            "type": "done",
            "session_id": session_id,
        }))

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
