"""Tests for autonomous consciousness loop."""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koclaw_agent.autonomous import (
    SCHEDULE_UPDATE_TOOL,
    AutonomousManager,
    _MESSAGE_RE,
)


# ── Helpers ──


def _make_persona():
    p = MagicMock()
    p.base_prompt = "あなたはここのんです。"
    return p


def _make_config(**overrides):
    cfg = {
        "default_interval_secs": 300,
        "min_interval_secs": 60,
        "max_interval_secs": 3600,
        "max_daily_messages": 5,
        "min_message_interval_secs": 60,
        "channel": "telegram",
        "target_id": "12345",
        "active_hours_start": "00:00",
        "active_hours_end": "23:59",
        "timezone": "Asia/Tokyo",
    }
    cfg.update(overrides)
    return cfg


def _make_manager(tmp_path, config_overrides=None, rag_memory=None, **kwargs):
    """Create an AutonomousManager with test defaults."""
    cfg = _make_config(
        state_file=str(tmp_path / "state.json"),
        **(config_overrides or {}),
    )
    return AutonomousManager(
        config=cfg,
        llm_router=kwargs.get("llm_router", MagicMock()),
        rag_memory=rag_memory,
        persona=kwargs.get("persona", _make_persona()),
        send_message_callback=kwargs.get("send_message_callback", AsyncMock()),
        execute_memory_tool=kwargs.get("execute_memory_tool", AsyncMock()),
    )


# ── Tool definition ──


class TestScheduleUpdateTool:
    def test_tool_name(self):
        assert SCHEDULE_UPDATE_TOOL["name"] == "schedule_update"

    def test_tool_schema(self):
        schema = SCHEDULE_UPDATE_TOOL["inputSchema"]
        assert "interval_mins" in schema["properties"]
        assert "reason" in schema["properties"]
        assert set(schema["required"]) == {"interval_mins", "reason"}

    def test_tool_mcp_server(self):
        assert SCHEDULE_UPDATE_TOOL["_mcp_server"] == "_autonomous"


# ── Message regex ──


class TestMessageRegex:
    def test_basic_match(self):
        text = "思考...[MESSAGE]こんにちは先生！[/MESSAGE]"
        m = _MESSAGE_RE.search(text)
        assert m is not None
        assert m.group(1).strip() == "こんにちは先生！"

    def test_multiline_message(self):
        text = "[MESSAGE]\n先生、\nお元気ですか？\n[/MESSAGE]"
        m = _MESSAGE_RE.search(text)
        assert m is not None
        assert "お元気ですか" in m.group(1)

    def test_no_match(self):
        text = "普通の思考です。[IDLE]"
        assert _MESSAGE_RE.search(text) is None

    def test_empty_message(self):
        text = "[MESSAGE][/MESSAGE]"
        m = _MESSAGE_RE.search(text)
        assert m is not None
        assert m.group(1).strip() == ""


# ── Interval management ──


class TestIntervalManagement:
    def test_update_interval(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.update_interval(10, "テスト")
        assert mgr._interval_secs == 600  # 10 * 60
        assert mgr._last_update_reason == "テスト"

    def test_clamp_min(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.update_interval(0, "too small")
        assert mgr._interval_secs == 60  # min_interval_secs

    def test_clamp_max(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.update_interval(999, "too big")
        assert mgr._interval_secs == 3600  # max_interval_secs

    def test_default_interval(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr._interval_secs == 300  # default_interval_secs


# ── State persistence ──


class TestStatePersistence:
    def test_save_and_load(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._interval_secs = 600
        mgr._thinking_count = 5
        mgr._last_update_reason = "test reason"
        mgr._save_state()

        # Create new instance — should load state
        mgr2 = _make_manager(tmp_path)
        assert mgr2._interval_secs == 600
        assert mgr2._thinking_count == 5
        assert mgr2._last_update_reason == "test reason"

    def test_load_missing_file(self, tmp_path):
        """No state file should use defaults."""
        mgr = _make_manager(tmp_path)
        assert mgr._interval_secs == 300
        assert mgr._thinking_count == 0

    def test_load_corrupted_file(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text("not json!!!", encoding="utf-8")
        # Should not crash, just use defaults
        mgr = _make_manager(tmp_path)
        assert mgr._interval_secs == 300

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        cfg = _make_config(state_file=str(nested / "state.json"))
        mgr = AutonomousManager(
            config=cfg,
            llm_router=MagicMock(),
            rag_memory=None,
            persona=_make_persona(),
            send_message_callback=AsyncMock(),
            execute_memory_tool=AsyncMock(),
        )
        mgr._save_state()
        assert (nested / "state.json").exists()

    def test_state_file_content(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._daily_message_count = 3
        mgr._last_message_date = "2026-03-08"
        mgr._save_state()

        data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert data["daily_message_count"] == 3
        assert data["last_message_date"] == "2026-03-08"


# ── Active hours ──


class TestActiveHours:
    def test_within_active_hours(self, tmp_path):
        mgr = _make_manager(tmp_path, {"active_hours_start": "00:00", "active_hours_end": "23:59"})
        assert mgr._is_active_hours() is True

    def test_outside_active_hours(self, tmp_path):
        mgr = _make_manager(tmp_path, {"active_hours_start": "25:00", "active_hours_end": "25:01"})
        assert mgr._is_active_hours() is False


# ── Proactive messaging ──


class TestProactiveMessaging:
    async def test_send_proactive_success(self, tmp_path):
        callback = AsyncMock()
        mgr = _make_manager(tmp_path, send_message_callback=callback)
        await mgr._try_send_proactive("テストメッセージ")
        callback.assert_called_once_with("telegram", "12345", "テストメッセージ")

    async def test_daily_limit(self, tmp_path):
        callback = AsyncMock()
        mgr = _make_manager(tmp_path, {"max_daily_messages": 2}, send_message_callback=callback)

        # Reset to today
        mgr._last_message_date = datetime.now().strftime("%Y-%m-%d")
        mgr._daily_message_count = 2

        await mgr._try_send_proactive("should not send")
        callback.assert_not_called()

    async def test_daily_counter_resets_on_new_day(self, tmp_path):
        callback = AsyncMock()
        mgr = _make_manager(tmp_path, {"max_daily_messages": 1}, send_message_callback=callback)

        mgr._last_message_date = "2020-01-01"  # Old date
        mgr._daily_message_count = 999

        await mgr._try_send_proactive("new day message")
        callback.assert_called_once()

    async def test_min_interval(self, tmp_path):
        callback = AsyncMock()
        mgr = _make_manager(
            tmp_path,
            {"min_message_interval_secs": 99999},
            send_message_callback=callback,
        )
        mgr._last_message_time = datetime.now().isoformat()

        await mgr._try_send_proactive("too soon")
        callback.assert_not_called()

    async def test_outside_active_hours_suppressed(self, tmp_path):
        callback = AsyncMock()
        mgr = _make_manager(
            tmp_path,
            {"active_hours_start": "25:00", "active_hours_end": "25:01"},
            send_message_callback=callback,
        )
        await mgr._try_send_proactive("should not send")
        callback.assert_not_called()

    async def test_send_updates_counters(self, tmp_path):
        callback = AsyncMock()
        mgr = _make_manager(tmp_path, send_message_callback=callback)
        await mgr._try_send_proactive("hello")
        assert mgr._daily_message_count == 1
        assert mgr._last_message_time is not None

    async def test_send_callback_error(self, tmp_path):
        callback = AsyncMock(side_effect=RuntimeError("network error"))
        mgr = _make_manager(tmp_path, send_message_callback=callback)
        # Should not raise
        await mgr._try_send_proactive("error message")
        assert mgr._daily_message_count == 0  # Not incremented on failure


# ── Thinking cycle ──


class TestThinking:
    async def test_think_idle(self, tmp_path):
        """LLM returns [IDLE], no message sent."""
        llm = MagicMock()

        async def fake_generate(**kwargs):
            yield "[IDLE]"

        llm.generate = fake_generate
        callback = AsyncMock()
        mgr = _make_manager(
            tmp_path,
            llm_router=llm,
            send_message_callback=callback,
        )

        await mgr._think()
        callback.assert_not_called()
        assert mgr._thinking_count == 1

    async def test_think_with_message(self, tmp_path):
        """LLM returns [MESSAGE]...[/MESSAGE], message sent."""
        llm = MagicMock()

        async def fake_generate(**kwargs):
            yield "思考...[MESSAGE]おはよう先生！[/MESSAGE]"

        llm.generate = fake_generate
        callback = AsyncMock()
        mgr = _make_manager(
            tmp_path,
            llm_router=llm,
            send_message_callback=callback,
        )

        await mgr._think()
        callback.assert_called_once_with("telegram", "12345", "おはよう先生！")

    async def test_think_with_memory_context(self, tmp_path):
        """Verify memories are loaded into thinking prompt."""
        llm = MagicMock()
        call_kwargs = {}

        async def fake_generate(**kwargs):
            call_kwargs.update(kwargs)
            yield "[IDLE]"

        llm.generate = fake_generate

        rag = AsyncMock()
        rag.reflect = AsyncMock(return_value=[
            {"id": "mem_001", "content": "先生は猫好き", "importance": 4,
             "category": "about_sensei", "timestamp": "2026-03-08T12:00:00"},
        ])

        mgr = _make_manager(tmp_path, llm_router=llm, rag_memory=rag)
        await mgr._think()

        # Verify the system prompt includes the memory
        sys_prompt = call_kwargs.get("system_prompt", "")
        assert "先生は猫好き" in sys_prompt

    async def test_think_increments_count(self, tmp_path):
        llm = MagicMock()

        async def fake_generate(**kwargs):
            yield "[IDLE]"

        llm.generate = fake_generate
        mgr = _make_manager(tmp_path, llm_router=llm)

        await mgr._think()
        await mgr._think()
        assert mgr._thinking_count == 2
        assert mgr._last_thinking_time is not None


# ── Lifecycle ──


class TestLifecycle:
    async def test_start_creates_task(self, tmp_path):
        mgr = _make_manager(tmp_path)
        # Patch _loop to avoid actual execution
        async def noop():
            await asyncio.sleep(999999)

        mgr._loop = noop
        mgr.start()
        assert mgr._task is not None
        mgr._task.cancel()

    async def test_stop_cancels_task(self, tmp_path):
        mgr = _make_manager(tmp_path)

        async def forever():
            await asyncio.sleep(999999)

        mgr._loop = forever
        mgr.start()
        assert mgr._task is not None

        await mgr.stop()
        assert mgr._task is None
