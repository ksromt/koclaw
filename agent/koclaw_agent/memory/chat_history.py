"""File-based conversation memory. Stores one JSON file per session."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from .base import BaseMemory


class FileMemory(BaseMemory):
    """File-based conversation memory.

    Each session is stored as a separate JSON file under `storage_dir`.
    Thread-safety is ensured via an asyncio lock on all read/write operations.
    """

    def __init__(self, storage_dir: str = "chat_history"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        logger.info(f"FileMemory initialized: {self.storage_dir}")

    def _session_path(self, session_id: str) -> Path:
        """Map a session ID to a safe filesystem path."""
        safe_name = session_id.replace(":", "_").replace("/", "_")
        return self.storage_dir / f"{safe_name}.json"

    async def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        path = self._session_path(session_id)
        if not path.exists():
            return []

        async with self._lock:
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            return messages[-limit:]

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        path = self._session_path(session_id)

        async with self._lock:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {
                    "session_id": session_id,
                    "created": datetime.now().isoformat(),
                    "messages": [],
                }

            data["messages"].append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            })
            data["updated"] = datetime.now().isoformat()

            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    async def clear_history(self, session_id: str) -> None:
        path = self._session_path(session_id)
        if not path.exists():
            return

        async with self._lock:
            path.unlink()

    async def list_sessions(self) -> list[str]:
        sessions = []
        for path in self.storage_dir.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(data.get("session_id", path.stem))
        return sessions
