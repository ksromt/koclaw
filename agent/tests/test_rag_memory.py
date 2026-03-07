"""Tests for ChromaDB-backed long-term memory (RagMemory)."""

import json

import pytest

import chromadb


# ── Fixtures ──


class MockEmbeddingFunction:
    """Deterministic embedding function for tests."""

    def name(self) -> str:
        return "mock"

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors = []
        for text in input:
            h = hash(text) % (2**32)
            vec = [(h >> i & 1) * 0.1 for i in range(384)]
            vectors.append(vec)
        return vectors

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)


def _fresh_client():
    """Create an EphemeralClient with clean collections."""
    client = chromadb.EphemeralClient()
    for name in ["kokoron_memories", "kokoron_archive"]:
        try:
            client.delete_collection(name)
        except Exception:
            pass
    return client


@pytest.fixture
def rag(tmp_path):
    """Create a RagMemory instance backed by a clean ephemeral ChromaDB."""
    from koclaw_agent.memory.rag_memory import RagMemory

    client = _fresh_client()
    ef = MockEmbeddingFunction()
    finetune_dir = tmp_path / "finetune_candidates"
    return RagMemory(
        finetune_candidates_path=str(finetune_dir),
        _client=client,
        _ef=ef,
    )


# ── Save & Search ──


async def test_save_returns_id(rag):
    mem_id = await rag.save(content="先生は猫が好き", importance=4, category="about_sensei")
    assert mem_id.startswith("mem_")
    assert "_001" in mem_id


async def test_save_increments_id(rag):
    id1 = await rag.save(content="fact 1", importance=2, category="knowledge")
    id2 = await rag.save(content="fact 2", importance=2, category="knowledge")
    # Sequence should increment
    assert id1 != id2
    assert "_001" in id1
    assert "_002" in id2


async def test_save_clamps_importance(rag):
    id1 = await rag.save(content="low", importance=0, category="conversation")
    id2 = await rag.save(content="high", importance=10, category="conversation")
    result = rag._memories.get(ids=[id1, id2], include=["metadatas"])
    assert result["metadatas"][0]["importance"] == 1
    assert result["metadatas"][1]["importance"] == 5


async def test_save_invalid_category_defaults(rag):
    mem_id = await rag.save(content="test", importance=3, category="invalid_cat")
    result = rag._memories.get(ids=[mem_id], include=["metadatas"])
    assert result["metadatas"][0]["category"] == "conversation"


async def test_search_empty(rag):
    results = await rag.search(query="anything")
    assert results == []


async def test_search_finds_saved(rag):
    await rag.save(content="先生は猫が好き", importance=3, category="about_sensei")
    results = await rag.search(query="猫")
    assert len(results) >= 1
    assert any("猫" in r["content"] for r in results)


async def test_search_min_importance_filter(rag):
    await rag.save(content="trivial info", importance=1, category="conversation")
    await rag.save(content="important info", importance=4, category="knowledge")
    results = await rag.search(query="info", min_importance=3)
    assert all(r["importance"] >= 3 for r in results)


async def test_search_category_filter(rag):
    await rag.save(content="about sensei", importance=3, category="about_sensei")
    await rag.save(content="knowledge item", importance=3, category="knowledge")
    results = await rag.search(query="item", category="knowledge")
    assert all(r["category"] == "knowledge" for r in results)


async def test_search_returns_distance(rag):
    await rag.save(content="test doc", importance=3, category="conversation")
    results = await rag.search(query="test")
    assert len(results) == 1
    assert "distance" in results[0]


# ── Classify ──


async def test_classify_updates_importance(rag):
    mem_id = await rag.save(content="test", importance=2, category="conversation")
    ok = await rag.classify(memory_id=mem_id, importance=5)
    assert ok is True
    result = rag._memories.get(ids=[mem_id], include=["metadatas"])
    assert result["metadatas"][0]["importance"] == 5


async def test_classify_updates_category(rag):
    mem_id = await rag.save(content="test", importance=2, category="conversation")
    ok = await rag.classify(memory_id=mem_id, category="about_sensei")
    assert ok is True
    result = rag._memories.get(ids=[mem_id], include=["metadatas"])
    assert result["metadatas"][0]["category"] == "about_sensei"


async def test_classify_updates_tags(rag):
    mem_id = await rag.save(content="test", importance=2, category="conversation")
    ok = await rag.classify(memory_id=mem_id, tags=["cat", "preference"])
    assert ok is True
    result = rag._memories.get(ids=[mem_id], include=["metadatas"])
    tags = json.loads(result["metadatas"][0]["tags"])
    assert tags == ["cat", "preference"]


async def test_classify_nonexistent_returns_false(rag):
    ok = await rag.classify(memory_id="mem_99999999_999")
    assert ok is False


async def test_classify_invalid_category_ignored(rag):
    mem_id = await rag.save(content="test", importance=2, category="conversation")
    ok = await rag.classify(memory_id=mem_id, category="bad_category")
    assert ok is True
    result = rag._memories.get(ids=[mem_id], include=["metadatas"])
    assert result["metadatas"][0]["category"] == "conversation"


# ── Forget (archive) ──


async def test_forget_moves_to_archive(rag):
    mem_id = await rag.save(content="to forget", importance=2, category="conversation")
    ok = await rag.forget(memory_id=mem_id, reason="outdated")
    assert ok is True
    # Gone from active
    assert rag._memories.count() == 0
    # Present in archive
    assert rag._archive.count() == 1
    archived = rag._archive.get(ids=[mem_id], include=["metadatas"])
    assert archived["metadatas"][0]["archive_reason"] == "outdated"


async def test_forget_nonexistent_returns_false(rag):
    ok = await rag.forget(memory_id="mem_99999999_999")
    assert ok is False


# ── Promote ──


async def test_promote_sets_importance_5(rag):
    mem_id = await rag.save(content="precious memory", importance=3, category="about_sensei")
    result = await rag.promote(memory_id=mem_id, reason="most important")
    assert result["id"] == mem_id
    # Check importance updated
    meta = rag._memories.get(ids=[mem_id], include=["metadatas"])["metadatas"][0]
    assert meta["importance"] == 5
    assert "promoted_at" in meta


async def test_promote_writes_finetune_candidate(rag, tmp_path):
    mem_id = await rag.save(content="soul memory", importance=3, category="about_sensei")
    result = await rag.promote(memory_id=mem_id, reason="forever")
    # Check finetune candidate file
    candidate_path = tmp_path / "finetune_candidates" / f"{mem_id}.json"
    assert candidate_path.exists()
    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert data["memory_id"] == mem_id
    assert data["conversations"][2]["value"] == "soul memory"


async def test_promote_nonexistent(rag):
    result = await rag.promote(memory_id="mem_99999999_999")
    assert "error" in result


# ── Reflect ──


async def test_reflect_empty(rag):
    results = await rag.reflect()
    assert results == []


async def test_reflect_returns_recent_first(rag):
    await rag.save(content="first", importance=2, category="conversation")
    await rag.save(content="second", importance=2, category="conversation")
    await rag.save(content="third", importance=2, category="conversation")
    results = await rag.reflect(limit=2)
    assert len(results) == 2
    assert results[0]["content"] == "third"
    assert results[1]["content"] == "second"


# ── Stats ──


async def test_stats_empty(rag):
    s = await rag.stats()
    assert s["total"] == 0
    assert s["by_category"] == {}
    assert s["latest_timestamp"] is None


async def test_stats_counts(rag):
    await rag.save(content="a", importance=2, category="about_sensei")
    await rag.save(content="b", importance=4, category="knowledge")
    await rag.save(content="c", importance=2, category="about_sensei")
    await rag.forget(memory_id=(await rag.reflect(limit=1))[0]["id"])

    s = await rag.stats()
    assert s["total"] == 2
    assert s["archived"] == 1
    assert s["by_category"].get("about_sensei", 0) >= 1
    assert s["latest_timestamp"] is not None


# ── Sequence counter recovery ──


async def test_seq_counter_recovery(tmp_path):
    """Verify that a new RagMemory instance recovers the max sequence."""
    from koclaw_agent.memory.rag_memory import RagMemory

    client = _fresh_client()
    ef = MockEmbeddingFunction()

    rag1 = RagMemory(
        finetune_candidates_path=str(tmp_path / "ft"),
        _client=client,
        _ef=ef,
    )
    await rag1.save(content="first", importance=2, category="conversation")
    await rag1.save(content="second", importance=2, category="conversation")

    # Create a new instance on the same client (simulates restart)
    rag2 = RagMemory(
        finetune_candidates_path=str(tmp_path / "ft"),
        _client=client,
        _ef=ef,
    )
    assert rag2._seq == 2
    id3 = await rag2.save(content="third", importance=2, category="conversation")
    assert "_003" in id3
