"""Tests for memory tool definitions and bridge-level execution."""

import json

import pytest

import chromadb

from koclaw_agent.memory_tools import MEMORY_TOOLS, is_memory_tool


# ── Tool Definition Tests ──


def test_memory_tools_count():
    """Verify we have exactly 7 memory tools."""
    assert len(MEMORY_TOOLS) == 7


def test_memory_tool_names():
    names = {t["name"] for t in MEMORY_TOOLS}
    assert names == {
        "memory_save",
        "memory_search",
        "memory_classify",
        "memory_forget",
        "memory_promote",
        "memory_reflect",
        "memory_stats",
    }


def test_memory_tool_schemas():
    """Verify all tools have required MCP-compatible fields."""
    for tool in MEMORY_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool.get("_mcp_server") == "_memory"


def test_save_schema():
    tool = next(t for t in MEMORY_TOOLS if t["name"] == "memory_save")
    schema = tool["inputSchema"]
    props = schema["properties"]
    assert "content" in props
    assert "importance" in props
    assert "category" in props
    assert "tags" in props
    assert set(schema["required"]) == {"content", "importance", "category"}


def test_search_schema():
    tool = next(t for t in MEMORY_TOOLS if t["name"] == "memory_search")
    schema = tool["inputSchema"]
    assert "query" in schema["properties"]
    assert schema["required"] == ["query"]


def test_classify_schema():
    tool = next(t for t in MEMORY_TOOLS if t["name"] == "memory_classify")
    schema = tool["inputSchema"]
    assert "memory_id" in schema["properties"]
    assert "importance" in schema["properties"]
    assert "category" in schema["properties"]
    assert "tags" in schema["properties"]
    assert schema["required"] == ["memory_id"]


def test_forget_schema():
    tool = next(t for t in MEMORY_TOOLS if t["name"] == "memory_forget")
    schema = tool["inputSchema"]
    assert "memory_id" in schema["properties"]
    assert "reason" in schema["properties"]
    assert schema["required"] == ["memory_id"]


def test_promote_schema():
    tool = next(t for t in MEMORY_TOOLS if t["name"] == "memory_promote")
    schema = tool["inputSchema"]
    assert "memory_id" in schema["properties"]
    assert "reason" in schema["properties"]
    assert schema["required"] == ["memory_id"]


def test_reflect_schema():
    tool = next(t for t in MEMORY_TOOLS if t["name"] == "memory_reflect")
    schema = tool["inputSchema"]
    assert "limit" in schema["properties"]
    assert "required" not in schema


def test_stats_schema():
    tool = next(t for t in MEMORY_TOOLS if t["name"] == "memory_stats")
    schema = tool["inputSchema"]
    assert schema["properties"] == {}
    assert "required" not in schema


def test_is_memory_tool():
    assert is_memory_tool("memory_save") is True
    assert is_memory_tool("memory_search") is True
    assert is_memory_tool("memory_classify") is True
    assert is_memory_tool("memory_forget") is True
    assert is_memory_tool("memory_promote") is True
    assert is_memory_tool("memory_reflect") is True
    assert is_memory_tool("memory_stats") is True
    assert is_memory_tool("scheduler_create_job") is False
    assert is_memory_tool("get_current_time") is False
    assert is_memory_tool("memory") is False  # no underscore suffix


# ── Bridge-Level Memory Tool Execution Tests ──


class MockEmbeddingFunction:
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
def bridge_with_rag(tmp_path):
    """Create a minimal AgentBridge with only rag_memory set."""
    from koclaw_agent.bridge import AgentBridge
    from koclaw_agent.memory.rag_memory import RagMemory

    bridge = AgentBridge.__new__(AgentBridge)
    client = _fresh_client()
    ef = MockEmbeddingFunction()
    bridge.rag_memory = RagMemory(
        finetune_candidates_path=str(tmp_path / "ft"),
        _client=client,
        _ef=ef,
    )
    return bridge


async def test_execute_memory_save(bridge_with_rag):
    result = await bridge_with_rag._execute_memory_tool(
        "memory_save",
        {"content": "先生は猫が好き", "importance": 4, "category": "about_sensei"},
    )
    assert "保存しました" in result
    assert "mem_" in result


async def test_execute_memory_search_empty(bridge_with_rag):
    result = await bridge_with_rag._execute_memory_tool(
        "memory_search",
        {"query": "猫"},
    )
    assert "見つかりませんでした" in result


async def test_execute_memory_search_finds(bridge_with_rag):
    await bridge_with_rag._execute_memory_tool(
        "memory_save",
        {"content": "先生は猫が好き", "importance": 3, "category": "about_sensei"},
    )
    result = await bridge_with_rag._execute_memory_tool(
        "memory_search",
        {"query": "猫"},
    )
    assert "検索結果" in result
    assert "猫" in result


async def test_execute_memory_classify(bridge_with_rag):
    save_result = await bridge_with_rag._execute_memory_tool(
        "memory_save",
        {"content": "test", "importance": 2, "category": "conversation"},
    )
    # Extract ID from result
    mem_id = save_result.split("ID: ")[1].rstrip(")")
    result = await bridge_with_rag._execute_memory_tool(
        "memory_classify",
        {"memory_id": mem_id, "importance": 5},
    )
    assert "更新しました" in result


async def test_execute_memory_forget(bridge_with_rag):
    save_result = await bridge_with_rag._execute_memory_tool(
        "memory_save",
        {"content": "forget me", "importance": 2, "category": "conversation"},
    )
    mem_id = save_result.split("ID: ")[1].rstrip(")")
    result = await bridge_with_rag._execute_memory_tool(
        "memory_forget",
        {"memory_id": mem_id, "reason": "outdated"},
    )
    assert "アーカイブしました" in result


async def test_execute_memory_promote(bridge_with_rag, tmp_path):
    save_result = await bridge_with_rag._execute_memory_tool(
        "memory_save",
        {"content": "soul memory", "importance": 3, "category": "about_sensei"},
    )
    mem_id = save_result.split("ID: ")[1].rstrip(")")
    result = await bridge_with_rag._execute_memory_tool(
        "memory_promote",
        {"memory_id": mem_id, "reason": "永遠に覚えていたい"},
    )
    assert "魂の記憶候補" in result


async def test_execute_memory_reflect_empty(bridge_with_rag):
    result = await bridge_with_rag._execute_memory_tool(
        "memory_reflect", {},
    )
    assert "まだありません" in result


async def test_execute_memory_reflect(bridge_with_rag):
    await bridge_with_rag._execute_memory_tool(
        "memory_save",
        {"content": "memory 1", "importance": 2, "category": "conversation"},
    )
    result = await bridge_with_rag._execute_memory_tool(
        "memory_reflect", {"limit": 10},
    )
    assert "最近の記憶" in result
    assert "memory 1" in result


async def test_execute_memory_stats(bridge_with_rag):
    await bridge_with_rag._execute_memory_tool(
        "memory_save",
        {"content": "a", "importance": 3, "category": "about_sensei"},
    )
    result = await bridge_with_rag._execute_memory_tool(
        "memory_stats", {},
    )
    assert "総数=1" in result
    assert "about_sensei" in result


async def test_execute_memory_no_rag():
    """Verify graceful error when rag_memory is None."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge.rag_memory = None
    result = await bridge._execute_memory_tool("memory_save", {"content": "test"})
    assert "not available" in result
