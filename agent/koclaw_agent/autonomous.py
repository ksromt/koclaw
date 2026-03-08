"""Autonomous consciousness loop for Kokoron.

Periodically triggers self-directed thinking where Kokoron can:
- Reflect on and organize memories
- Adjust her own thinking interval
- Proactively send messages to sensei
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from .mcp_host.tool_prompt import build_tool_prompt, parse_tool_call
from .memory_tools import MEMORY_TOOLS, is_memory_tool
from .providers.openai_provider import _strip_internal_tags


SCHEDULE_UPDATE_TOOL: dict = {
    "name": "schedule_update",
    "description": (
        "自分の次の思考ループまでの間隔を変更する。"
        "忙しい・興味深い時は短く、静かな時は長くできる。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "interval_mins": {
                "type": "integer",
                "description": "次の思考までの分数（1-180の範囲）",
            },
            "reason": {
                "type": "string",
                "description": "なぜ変更するのか（記録用）",
            },
        },
        "required": ["interval_mins", "reason"],
    },
    "_mcp_server": "_autonomous",
}

_MESSAGE_RE = re.compile(r"\[MESSAGE\](.*?)\[/MESSAGE\]", re.DOTALL)


class AutonomousManager:
    """Manages Kokoron's self-directed thinking loop."""

    def __init__(
        self,
        config: dict,
        llm_router,
        rag_memory,
        persona,
        send_message_callback: Callable[[str, str, str], Awaitable[None]],
        execute_memory_tool: Callable[[str, dict], Awaitable[str]],
    ):
        self._config = config
        self._llm_router = llm_router
        self._rag_memory = rag_memory
        self._persona = persona
        self._send_message = send_message_callback
        self._execute_memory_tool = execute_memory_tool

        # Interval bounds from config
        self._min_interval = config.get("min_interval_secs", 60)
        self._max_interval = config.get("max_interval_secs", 10800)
        self._default_interval = config.get("default_interval_secs", 1800)

        # Proactive message limits
        self._max_daily_messages = config.get("max_daily_messages", 5)
        self._min_message_interval = config.get("min_message_interval_secs", 3600)

        # Target channel for proactive messages
        self._channel = config.get("channel", "telegram")
        self._target_id = config.get("target_id", "")

        # Active hours
        self._active_start = config.get("active_hours_start", "08:00")
        self._active_end = config.get("active_hours_end", "23:00")
        self._timezone = config.get("timezone", "Asia/Tokyo")

        # State
        self._interval_secs: int = self._default_interval
        self._last_update_reason: str = "初回起動"
        self._last_thinking_time: str | None = None
        self._thinking_count: int = 0
        self._daily_message_count: int = 0
        self._last_message_date: str | None = None
        self._last_message_time: str | None = None
        self._last_thinking_summary: str | None = None

        self._state_file = Path(
            config.get("state_file", "./data/state/autonomous_state.json")
        )
        self._load_state()

        self._task: asyncio.Task | None = None

    # ── Lifecycle ──

    def start(self):
        """Start the autonomous thinking loop as a background task."""
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"Autonomous loop started: interval={self._interval_secs}s, "
            f"channel={self._channel}, target={self._target_id}"
        )

    async def stop(self):
        """Gracefully stop the thinking loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Autonomous loop stopped")

    # ── Main loop ──

    async def _loop(self):
        """Run indefinitely: sleep → active hours check → think."""
        while True:
            try:
                await asyncio.sleep(self._interval_secs)
                if not self._is_active_hours():
                    logger.debug("Outside active hours, skipping autonomous thinking")
                    continue
                await self._think()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Autonomous thinking error: {e}")

    def _is_active_hours(self) -> bool:
        """Check if current time is within configured active hours."""
        now = datetime.now()
        now_str = now.strftime("%H:%M")
        return self._active_start <= now_str <= self._active_end

    @property
    def last_thinking_summary(self) -> str | None:
        """Most recent non-IDLE thinking summary for chat context injection."""
        return self._last_thinking_summary

    # ── Thinking ──

    async def _think(self):
        """Execute one thinking cycle."""
        logger.info(f"Autonomous thinking #{self._thinking_count + 1} starting")

        # Get recent memories for reflection
        memory_context = ""
        if self._rag_memory:
            try:
                recent = await self._rag_memory.reflect(limit=10)
                if recent:
                    lines = []
                    for r in recent:
                        stars = "*" * r["importance"]
                        lines.append(
                            f"- [{r['id']}] {stars} {r['content']} "
                            f"({r['category']}, {r['timestamp'][:10]})"
                        )
                    memory_context = "\n".join(lines)
            except Exception as e:
                logger.warning(f"Failed to load memories for thinking: {e}")

        # Build tool prompt for autonomous tools
        autonomous_tools = MEMORY_TOOLS + [SCHEDULE_UPDATE_TOOL]
        tool_prompt = build_tool_prompt(autonomous_tools)

        # Build the thinking prompt
        base_prompt = self._persona.base_prompt
        last_time = self._last_thinking_time or "（初回）"
        last_reason = self._last_update_reason

        system_prompt = f"""{base_prompt}

あなたは今、自由に考える時間です。

【最近の記憶】
{memory_context or "（まだ記憶がありません）"}

【前回の思考】
時刻: {last_time}
間隔変更理由: {last_reason}

{tool_prompt}

【判断してください】
- 整理すべき記憶はある？
- 気になること、考えたいことはある？
- 先生に共有したいことはある？

先生に共有したいことがあれば [MESSAGE] タグで囲んでメッセージを書いてください：
[MESSAGE]先生に送りたい内容[/MESSAGE]

特にない場合は [IDLE] とだけ返してください。
無理にメッセージを作る必要はありません。"""

        # LLM generation with tool execution loop (max 5 iterations)
        current_text = "自由思考の時間です。記憶を振り返り、判断してください。"
        full_response = ""
        thinking_actions: list[str] = []

        for _iteration in range(5):
            iteration_response = ""
            async for chunk in self._llm_router.generate(
                text=current_text,
                session_id="autonomous",
                permission="Admin",
                system_prompt=system_prompt,
            ):
                text_content = chunk
                if hasattr(chunk, "text"):
                    text_content = chunk.text or ""
                if text_content:
                    iteration_response += text_content

            # Clean thinking artifacts
            iteration_response = _strip_internal_tags(iteration_response)

            # Check for tool call
            parsed = parse_tool_call(iteration_response)
            if parsed is None:
                full_response += iteration_response
                break

            tool_name = parsed.get("tool", "")
            tool_args = parsed.get("arguments", {})
            logger.info(f"Autonomous tool call: {tool_name}({tool_args})")

            # Execute tool
            if tool_name == "schedule_update":
                self.update_interval(
                    tool_args.get("interval_mins", 30),
                    tool_args.get("reason", ""),
                )
                tool_result = (
                    f"間隔を{self._interval_secs // 60}分に変更しました。"
                )
            elif is_memory_tool(tool_name):
                tool_result = await self._execute_memory_tool(
                    tool_name, tool_args
                )
            else:
                tool_result = f"Error: Unknown tool: {tool_name}"
                logger.warning(f"Unknown tool in autonomous thinking: {tool_name}")

            logger.info(f"Autonomous tool result: {tool_result[:200]}")
            thinking_actions.append(f"{tool_name}: {tool_result[:150]}")

            # Feed result back for next iteration
            current_text = f"[Tool Result: {tool_name}]\n{tool_result}"

        # Update state
        self._thinking_count += 1
        self._last_thinking_time = datetime.now().isoformat()

        # Build and persist thinking summary
        is_idle = "[IDLE]" in full_response and not thinking_actions
        if not is_idle and (thinking_actions or full_response.strip()):
            summary_lines = []
            for action in thinking_actions:
                summary_lines.append(f"- {action}")
            clean_text = full_response.replace("[IDLE]", "").strip()[:300]
            if clean_text:
                summary_lines.append(f"考えたこと: {clean_text}")

            self._last_thinking_summary = (
                f"時刻: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                + "\n".join(summary_lines)
            )

            # Save to RAG as self-reflection for cross-session memory
            if self._rag_memory and summary_lines:
                try:
                    await self._rag_memory.save(
                        content="【自主思考記録】" + "\n".join(summary_lines),
                        importance=2,
                        category="self_reflection",
                        tags=["autonomous_thinking"],
                        source_session="autonomous",
                    )
                except Exception as e:
                    logger.warning(f"Failed to save thinking reflection: {e}")

        self._save_state()

        # Check for proactive message
        message_match = _MESSAGE_RE.search(full_response)
        if message_match:
            proactive_text = message_match.group(1).strip()
            if proactive_text:
                await self._try_send_proactive(proactive_text)
        elif "[IDLE]" in full_response:
            logger.info("Autonomous thinking: IDLE (no action needed)")
        else:
            logger.info(
                f"Autonomous thinking complete: "
                f"{full_response[:100] if full_response else '(empty)'}"
            )

    # ── Proactive messaging ──

    async def _try_send_proactive(self, message: str):
        """Send a proactive message if rate limits allow."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # Reset daily counter on new day
        if self._last_message_date != today:
            self._daily_message_count = 0
            self._last_message_date = today

        # Check daily limit
        if self._daily_message_count >= self._max_daily_messages:
            logger.info(
                f"Proactive message suppressed: daily limit "
                f"({self._daily_message_count}/{self._max_daily_messages})"
            )
            return

        # Check minimum interval
        if self._last_message_time:
            try:
                last_dt = datetime.fromisoformat(self._last_message_time)
                elapsed = (now - last_dt).total_seconds()
                if elapsed < self._min_message_interval:
                    logger.info(
                        f"Proactive message suppressed: too soon "
                        f"({elapsed:.0f}s < {self._min_message_interval}s)"
                    )
                    return
            except (ValueError, TypeError):
                pass

        # Check active hours
        if not self._is_active_hours():
            logger.info("Proactive message suppressed: outside active hours")
            return

        # Send
        logger.info(f"Sending proactive message: {message[:100]}")
        try:
            await self._send_message(
                self._channel, self._target_id, message
            )
            self._daily_message_count += 1
            self._last_message_time = now.isoformat()
            self._save_state()
        except Exception as e:
            logger.error(f"Failed to send proactive message: {e}")

    # ── Interval management ──

    def update_interval(self, interval_mins: int, reason: str):
        """Update the thinking interval (called by schedule_update tool)."""
        min_mins = self._min_interval // 60
        max_mins = self._max_interval // 60
        clamped = max(min_mins, min(max_mins, interval_mins))
        self._interval_secs = clamped * 60
        self._last_update_reason = reason
        self._save_state()
        logger.info(
            f"Autonomous interval updated: {clamped}min "
            f"(requested: {interval_mins}min), reason: {reason}"
        )

    # ── State persistence ──

    def _load_state(self):
        """Load persisted state from disk."""
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            self._interval_secs = data.get("interval_secs", self._default_interval)
            self._last_update_reason = data.get("last_update_reason", "初回起動")
            self._last_thinking_time = data.get("last_thinking_time")
            self._thinking_count = data.get("thinking_count", 0)
            self._daily_message_count = data.get("daily_message_count", 0)
            self._last_message_date = data.get("last_message_date")
            self._last_message_time = data.get("last_message_time")
            self._last_thinking_summary = data.get("last_thinking_summary")
            logger.info(
                f"Autonomous state loaded: interval={self._interval_secs}s, "
                f"count={self._thinking_count}"
            )
        except Exception as e:
            logger.warning(f"Failed to load autonomous state: {e}")

    def _save_state(self):
        """Persist current state to disk."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "interval_secs": self._interval_secs,
            "last_update_reason": self._last_update_reason,
            "last_thinking_time": self._last_thinking_time,
            "thinking_count": self._thinking_count,
            "daily_message_count": self._daily_message_count,
            "last_message_date": self._last_message_date,
            "last_message_time": self._last_message_time,
            "last_thinking_summary": self._last_thinking_summary,
        }
        try:
            self._state_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save autonomous state: {e}")
