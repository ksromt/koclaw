"""ChromaDB-backed long-term memory for Kokoron."""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from loguru import logger


VALID_CATEGORIES = frozenset({
    "about_sensei", "conversation", "knowledge",
    "observation", "self_reflection",
})


class RagMemory:
    """ChromaDB-backed long-term memory for Kokoron.

    Two collections:
    - kokoron_memories: active memories
    - kokoron_archive: forgotten memories (moved, not deleted)

    All ChromaDB operations are synchronous; async wrappers use
    asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(
        self,
        db_path: str = "./data/chromadb",
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        finetune_candidates_path: str = "./data/finetune_candidates",
        *,
        _client=None,
        _ef=None,
    ):
        import chromadb

        if _client is not None:
            self._client = _client
        else:
            os.makedirs(db_path, exist_ok=True)
            self._client = chromadb.PersistentClient(path=db_path)

        if _ef is not None:
            self._ef = _ef
        else:
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )
            self._ef = SentenceTransformerEmbeddingFunction(
                model_name=embedding_model,
            )

        self._memories = self._client.get_or_create_collection(
            name="kokoron_memories",
            embedding_function=self._ef,
        )
        self._archive = self._client.get_or_create_collection(
            name="kokoron_archive",
            embedding_function=self._ef,
        )

        self._finetune_path = Path(finetune_candidates_path)
        self._finetune_path.mkdir(parents=True, exist_ok=True)

        self._seq = self._scan_max_seq()
        self._lock = asyncio.Lock()

        logger.info(
            f"RagMemory initialized: "
            f"active={self._memories.count()}, "
            f"archived={self._archive.count()}, "
            f"next_seq={self._seq + 1}"
        )

    # ── ID generation ──

    def _scan_max_seq(self) -> int:
        """Scan existing memory IDs to find the max sequence number."""
        if self._memories.count() == 0:
            return 0
        result = self._memories.get(include=[])
        max_seq = 0
        for mid in result["ids"]:
            m = re.match(r"mem_\d{8}_(\d+)", mid)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
        return max_seq

    def _next_id(self) -> str:
        """Generate next memory ID: mem_YYYYMMDD_NNN."""
        self._seq += 1
        return f"mem_{datetime.now().strftime('%Y%m%d')}_{self._seq:03d}"

    # ── Core operations ──

    async def save(
        self,
        content: str,
        importance: int = 3,
        category: str = "conversation",
        tags: list[str] | None = None,
        source_session: str | None = None,
    ) -> str:
        """Save a memory. Returns the memory_id."""
        importance = max(1, min(5, importance))
        if category not in VALID_CATEGORIES:
            category = "conversation"

        async with self._lock:
            memory_id = self._next_id()

        metadata: dict = {
            "importance": importance,
            "category": category,
            "timestamp": datetime.now().isoformat(),
            "tags": json.dumps(tags or [], ensure_ascii=False),
        }
        if source_session:
            metadata["source_session"] = source_session

        await asyncio.to_thread(
            self._memories.add,
            ids=[memory_id],
            documents=[content],
            metadatas=[metadata],
        )

        logger.info(
            f"Memory saved: {memory_id} [{category}/{'*' * importance}] "
            f"{content[:60]}"
        )
        return memory_id

    async def search(
        self,
        query: str,
        limit: int = 5,
        min_importance: int = 1,
        category: str | None = None,
    ) -> list[dict]:
        """Semantic search memories. Returns list of memory dicts."""
        count = self._memories.count()
        if count == 0:
            return []

        where_filter = None
        conditions = []
        if min_importance > 1:
            conditions.append({"importance": {"$gte": min_importance}})
        if category and category in VALID_CATEGORIES:
            conditions.append({"category": category})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        result = await asyncio.to_thread(
            self._memories.query,
            query_texts=[query],
            n_results=min(limit, count),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        memories = []
        if result["ids"] and result["ids"][0]:
            for i, mid in enumerate(result["ids"][0]):
                meta = result["metadatas"][0][i]
                memories.append({
                    "id": mid,
                    "content": result["documents"][0][i],
                    "importance": meta.get("importance", 3),
                    "category": meta.get("category", ""),
                    "timestamp": meta.get("timestamp", ""),
                    "tags": json.loads(meta.get("tags", "[]")),
                    "distance": result["distances"][0][i],
                })

        return memories

    async def classify(
        self,
        memory_id: str,
        importance: int | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """Update a memory's metadata."""
        result = await asyncio.to_thread(
            self._memories.get,
            ids=[memory_id],
            include=["metadatas"],
        )
        if not result["ids"]:
            return False

        meta = result["metadatas"][0]
        if importance is not None:
            meta["importance"] = max(1, min(5, importance))
        if category is not None and category in VALID_CATEGORIES:
            meta["category"] = category
        if tags is not None:
            meta["tags"] = json.dumps(tags, ensure_ascii=False)

        await asyncio.to_thread(
            self._memories.update,
            ids=[memory_id],
            metadatas=[meta],
        )
        return True

    async def forget(self, memory_id: str, reason: str = "") -> bool:
        """Move a memory to archive (not deleted)."""
        result = await asyncio.to_thread(
            self._memories.get,
            ids=[memory_id],
            include=["documents", "metadatas"],
        )
        if not result["ids"]:
            return False

        meta = result["metadatas"][0]
        meta["archived_at"] = datetime.now().isoformat()
        meta["archive_reason"] = reason

        await asyncio.to_thread(
            self._archive.add,
            ids=[memory_id],
            documents=result["documents"],
            metadatas=[meta],
        )
        await asyncio.to_thread(
            self._memories.delete,
            ids=[memory_id],
        )

        logger.info(f"Memory archived: {memory_id} reason={reason}")
        return True

    async def promote(self, memory_id: str, reason: str = "") -> dict:
        """Mark as soul memory (importance=5) and write finetune candidate."""
        result = await asyncio.to_thread(
            self._memories.get,
            ids=[memory_id],
            include=["documents", "metadatas"],
        )
        if not result["ids"]:
            return {"id": memory_id, "error": "not found"}

        meta = result["metadatas"][0]
        meta["importance"] = 5
        meta["promoted_at"] = datetime.now().isoformat()
        meta["promote_reason"] = reason

        await asyncio.to_thread(
            self._memories.update,
            ids=[memory_id],
            metadatas=[meta],
        )

        # Write finetune candidate (ShareGPT format)
        candidate = {
            "conversations": [
                {
                    "from": "system",
                    "value": "You are Kokoron, recalling an important memory.",
                },
                {"from": "human", "value": "What do you remember about this?"},
                {"from": "gpt", "value": result["documents"][0]},
            ],
            "memory_id": memory_id,
            "category": meta.get("category", ""),
            "promoted_at": meta["promoted_at"],
            "reason": reason,
        }

        candidate_path = self._finetune_path / f"{memory_id}.json"
        candidate_path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(f"Memory promoted: {memory_id} -> finetune candidate")
        return {"id": memory_id, "path": str(candidate_path)}

    async def reflect(self, limit: int = 20) -> list[dict]:
        """Get recent memories sorted by timestamp descending."""
        if self._memories.count() == 0:
            return []

        result = await asyncio.to_thread(
            self._memories.get,
            include=["documents", "metadatas"],
        )

        memories = []
        for i, mid in enumerate(result["ids"]):
            meta = result["metadatas"][i]
            memories.append({
                "id": mid,
                "content": result["documents"][i],
                "importance": meta.get("importance", 3),
                "category": meta.get("category", ""),
                "timestamp": meta.get("timestamp", ""),
                "tags": json.loads(meta.get("tags", "[]")),
            })

        memories.sort(key=lambda m: m["timestamp"], reverse=True)
        return memories[:limit]

    async def stats(self) -> dict:
        """Return memory statistics."""
        count = self._memories.count()
        if count == 0:
            return {
                "total": 0,
                "archived": self._archive.count(),
                "by_category": {},
                "by_importance": {},
                "latest_timestamp": None,
            }

        result = await asyncio.to_thread(
            self._memories.get,
            include=["metadatas"],
        )

        by_category: dict[str, int] = {}
        by_importance: dict[int, int] = {}
        latest = ""

        for meta in result["metadatas"]:
            cat = meta.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1

            imp = meta.get("importance", 3)
            by_importance[imp] = by_importance.get(imp, 0) + 1

            ts = meta.get("timestamp", "")
            if ts > latest:
                latest = ts

        return {
            "total": count,
            "archived": self._archive.count(),
            "by_category": by_category,
            "by_importance": by_importance,
            "latest_timestamp": latest or None,
        }
