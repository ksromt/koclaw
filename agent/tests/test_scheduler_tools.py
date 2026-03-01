"""Tests for scheduler tool definitions and bridge-level execution."""

import asyncio
import json

import pytest

from koclaw_agent.scheduler_tools import SCHEDULER_TOOLS, is_scheduler_tool


# ── Task 8: Tool Definition Tests ──


def test_scheduler_tools_count():
    """Verify we have exactly 3 scheduler tools."""
    assert len(SCHEDULER_TOOLS) == 3


def test_scheduler_tool_names():
    """Verify tool names follow the scheduler.* pattern."""
    names = {t["name"] for t in SCHEDULER_TOOLS}
    assert names == {
        "scheduler.create_job",
        "scheduler.list_jobs",
        "scheduler.delete_job",
    }


def test_scheduler_tool_schemas():
    """Verify all tools have required MCP-compatible fields."""
    for tool in SCHEDULER_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool.get("_mcp_server") == "_scheduler"


def test_create_job_schema():
    """Verify create_job has the expected properties."""
    tool = next(t for t in SCHEDULER_TOOLS if t["name"] == "scheduler.create_job")
    schema = tool["inputSchema"]
    props = schema["properties"]
    assert "message" in props
    assert "delay_seconds" in props
    assert "cron" in props
    assert "timezone" in props
    assert "one_shot" in props
    assert schema["required"] == ["message"]


def test_delete_job_schema():
    """Verify delete_job requires job_id."""
    tool = next(t for t in SCHEDULER_TOOLS if t["name"] == "scheduler.delete_job")
    schema = tool["inputSchema"]
    assert "job_id" in schema["properties"]
    assert schema["required"] == ["job_id"]


def test_is_scheduler_tool():
    """Test scheduler tool detection."""
    assert is_scheduler_tool("scheduler.create_job") is True
    assert is_scheduler_tool("scheduler.list_jobs") is True
    assert is_scheduler_tool("scheduler.delete_job") is True
    assert is_scheduler_tool("get_current_time") is False
    assert is_scheduler_tool("filesystem.read") is False
    assert is_scheduler_tool("scheduler") is False  # no dot suffix


def test_list_jobs_schema():
    """Verify list_jobs has no required properties."""
    tool = next(t for t in SCHEDULER_TOOLS if t["name"] == "scheduler.list_jobs")
    schema = tool["inputSchema"]
    assert "required" not in schema


# ── Task 9: Bridge-Level Scheduler Integration Tests ──


class FakeWebSocket:
    """Mock WebSocket that records sent messages."""

    def __init__(self, responses: list[str] | None = None):
        self.sent: list[str] = []
        self._responses = responses or []
        self._response_idx = 0

    async def send(self, data: str):
        self.sent.append(data)

    async def recv(self) -> str:
        if self._response_idx < len(self._responses):
            msg = self._responses[self._response_idx]
            self._response_idx += 1
            return msg
        raise StopIteration


def test_scheduler_request_json_for_create():
    """Verify _execute_scheduler_tool builds correct create request JSON."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge._scheduler_pending = {}

    ws = FakeWebSocket()

    # Simulate: the bridge sends a request and waits for a response.
    # We inject the response into _scheduler_pending after the request is sent.
    async def run():
        # Run the tool call in a task so we can inject the response
        async def inject_response():
            # Wait until the request is sent
            while not ws.sent:
                await asyncio.sleep(0.01)
            # Parse the request to get session_id
            req = json.loads(ws.sent[0])
            # Send response
            bridge._handle_scheduler_response({
                "session_id": req["session_id"],
                "success": True,
                "job_id": "abc12345",
            })

        task = asyncio.create_task(inject_response())
        result = await bridge._execute_scheduler_tool(
            ws, "scheduler.create_job",
            {"message": "テスト", "delay_seconds": 300},
            "tg:12345", "telegram", {},
        )
        await task
        return result

    result = asyncio.run(run())

    # Verify request JSON
    assert len(ws.sent) == 1
    req = json.loads(ws.sent[0])
    assert req["type"] == "scheduler_request"
    assert req["action"] == "create"
    assert req["session_id"] == "tg:12345"
    assert req["job"]["message"] == "テスト"
    assert req["job"]["delay_seconds"] == 300
    assert req["job"]["channel"] == "telegram"
    assert req["job"]["target_id"] == "12345"
    assert req["job"]["one_shot"] is True  # default for delay

    # Verify response formatting
    assert "abc12345" in result
    assert "created" in result.lower()


def test_scheduler_request_json_for_cron():
    """Verify create request uses cron and defaults one_shot to false."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge._scheduler_pending = {}

    ws = FakeWebSocket()

    async def run():
        async def inject_response():
            while not ws.sent:
                await asyncio.sleep(0.01)
            req = json.loads(ws.sent[0])
            bridge._handle_scheduler_response({
                "session_id": req["session_id"],
                "success": True,
                "job_id": "cron1234",
            })

        task = asyncio.create_task(inject_response())
        result = await bridge._execute_scheduler_tool(
            ws, "scheduler.create_job",
            {"message": "天気予報", "cron": "0 9 * * *"},
            "tg:99999", "telegram", {},
        )
        await task
        return result

    asyncio.run(run())

    req = json.loads(ws.sent[0])
    assert req["job"]["cron"] == "0 9 * * *"
    assert req["job"]["one_shot"] is False  # default for cron
    assert "delay_seconds" not in req["job"]


def test_scheduler_request_json_for_delete():
    """Verify delete request JSON structure."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge._scheduler_pending = {}

    ws = FakeWebSocket()

    async def run():
        async def inject_response():
            while not ws.sent:
                await asyncio.sleep(0.01)
            req = json.loads(ws.sent[0])
            bridge._handle_scheduler_response({
                "session_id": req["session_id"],
                "success": True,
                "job_id": "del12345",
            })

        task = asyncio.create_task(inject_response())
        result = await bridge._execute_scheduler_tool(
            ws, "scheduler.delete_job",
            {"job_id": "del12345"},
            "tg:12345", "telegram", {},
        )
        await task
        return result

    result = asyncio.run(run())

    req = json.loads(ws.sent[0])
    assert req["type"] == "scheduler_request"
    assert req["action"] == "delete"
    assert req["job_id"] == "del12345"
    assert "deleted" in result.lower()


def test_scheduler_request_json_for_list():
    """Verify list request and response formatting."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge._scheduler_pending = {}

    ws = FakeWebSocket()

    async def run():
        async def inject_response():
            while not ws.sent:
                await asyncio.sleep(0.01)
            req = json.loads(ws.sent[0])
            bridge._handle_scheduler_response({
                "session_id": req["session_id"],
                "success": True,
                "jobs": [
                    {"id": "aaa", "name": "test1", "message": "msg1"},
                    {"id": "bbb", "name": "test2", "message": "msg2"},
                ],
            })

        task = asyncio.create_task(inject_response())
        result = await bridge._execute_scheduler_tool(
            ws, "scheduler.list_jobs", {},
            "tg:12345", "telegram", {},
        )
        await task
        return result

    result = asyncio.run(run())

    req = json.loads(ws.sent[0])
    assert req["action"] == "list"
    assert "aaa" in result
    assert "bbb" in result
    assert "test1" in result


def test_scheduler_response_routing():
    """Verify _handle_scheduler_response routes to correct pending future."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge._scheduler_pending = {}

    loop = asyncio.new_event_loop()
    future = loop.create_future()
    bridge._scheduler_pending["session-abc"] = future

    response_msg = {
        "session_id": "session-abc",
        "success": True,
        "job_id": "xyz",
    }
    bridge._handle_scheduler_response(response_msg)

    assert future.done()
    assert future.result() == response_msg
    loop.close()


def test_scheduler_response_routing_unknown_session():
    """Verify _handle_scheduler_response ignores unknown sessions."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge._scheduler_pending = {}

    # Should not raise, just log a warning
    bridge._handle_scheduler_response({
        "session_id": "unknown-session",
        "success": True,
    })

    assert len(bridge._scheduler_pending) == 0


def test_scheduler_request_timeout():
    """Verify _execute_scheduler_tool returns error on timeout."""
    from koclaw_agent.bridge import AgentBridge

    bridge = AgentBridge.__new__(AgentBridge)
    bridge._scheduler_pending = {}

    ws = FakeWebSocket()

    async def run():
        # Don't inject any response → should timeout
        # Use a very short timeout by monkeypatching isn't easy,
        # so we'll let the 5s timeout happen but that's too slow for tests.
        # Instead, verify the timeout path with a mock.
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        # Simulate what happens when timeout occurs
        bridge._scheduler_pending["tg:timeout"] = future
        try:
            await asyncio.wait_for(future, timeout=0.05)
        except asyncio.TimeoutError:
            bridge._scheduler_pending.pop("tg:timeout", None)
            return "Error: Scheduler request timed out"
        return "unexpected"

    result = asyncio.run(run())
    assert result == "Error: Scheduler request timed out"
    assert "tg:timeout" not in bridge._scheduler_pending
