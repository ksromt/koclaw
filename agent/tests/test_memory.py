"""Tests for conversation memory system."""

import pytest

from koclaw_agent.memory import FileMemory


@pytest.fixture
def memory(tmp_path):
    return FileMemory(storage_dir=str(tmp_path / "test_history"))


@pytest.mark.asyncio
async def test_add_and_get(memory):
    await memory.add_message("sess1", "user", "Hello")
    await memory.add_message("sess1", "assistant", "Hi there!")
    history = await memory.get_history("sess1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Hi there!"


@pytest.mark.asyncio
async def test_separate_sessions(memory):
    await memory.add_message("sess1", "user", "Message A")
    await memory.add_message("sess2", "user", "Message B")
    h1 = await memory.get_history("sess1")
    h2 = await memory.get_history("sess2")
    assert len(h1) == 1
    assert len(h2) == 1
    assert h1[0]["content"] == "Message A"
    assert h2[0]["content"] == "Message B"


@pytest.mark.asyncio
async def test_empty_session(memory):
    history = await memory.get_history("nonexistent")
    assert history == []


@pytest.mark.asyncio
async def test_history_limit(memory):
    for i in range(100):
        await memory.add_message("sess1", "user", f"msg{i}")
    history = await memory.get_history("sess1", limit=10)
    assert len(history) == 10
    assert history[0]["content"] == "msg90"
    assert history[-1]["content"] == "msg99"


@pytest.mark.asyncio
async def test_clear_history(memory):
    await memory.add_message("sess1", "user", "Hello")
    await memory.clear_history("sess1")
    history = await memory.get_history("sess1")
    assert history == []


@pytest.mark.asyncio
async def test_session_id_with_colons(memory):
    """Session IDs from Telegram look like 'tg:12345' — colons are safe-named."""
    await memory.add_message("tg:12345", "user", "Hello via Telegram")
    history = await memory.get_history("tg:12345")
    assert len(history) == 1
    assert history[0]["content"] == "Hello via Telegram"


@pytest.mark.asyncio
async def test_list_sessions(memory):
    await memory.add_message("sess1", "user", "A")
    await memory.add_message("sess2", "user", "B")
    sessions = await memory.list_sessions()
    assert set(sessions) == {"sess1", "sess2"}
