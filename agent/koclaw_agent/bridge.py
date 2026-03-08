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

from .autonomous import AutonomousManager
from .expression import extract_expressions
from .llm_router import LLMRouter
from .mcp_host.server_manager import McpServerManager
from .mcp_host.tool_permissions import ToolPermissionChecker
from .mcp_host.tool_prompt import build_tool_prompt, parse_tool_call
from .memory import FileMemory
from .memory_tools import MEMORY_TOOLS, is_memory_tool
from .persona import Persona
from .scheduler_tools import SCHEDULER_TOOLS, is_scheduler_tool
from .self_check import startup_self_check
from .self_improving import SelfImproving, LearningEntry

try:
    from .memory.rag_memory import RagMemory
    _HAS_RAG = True
except ImportError:
    _HAS_RAG = False


# Common UTC offset → IANA timezone mapping (covers most users)
_UTC_OFFSET_TO_IANA: dict[int, str] = {
    -12: "Pacific/Baker_Island", -11: "Pacific/Pago_Pago",
    -10: "Pacific/Honolulu", -9: "America/Anchorage",
    -8: "America/Los_Angeles", -7: "America/Denver",
    -6: "America/Chicago", -5: "America/New_York",
    -4: "America/Halifax", -3: "America/Sao_Paulo",
    0: "Europe/London", 1: "Europe/Berlin", 2: "Europe/Helsinki",
    3: "Europe/Moscow", 4: "Asia/Dubai", 5: "Asia/Karachi",
    8: "Asia/Shanghai", 9: "Asia/Tokyo", 10: "Australia/Sydney",
    12: "Pacific/Auckland",
}


def _detect_iana_timezone() -> str:
    """Detect the system's IANA timezone name (e.g., 'Asia/Tokyo').

    Uses UTC offset to map to a common IANA name. Falls back to 'Asia/Tokyo'.
    """
    import datetime

    try:
        offset = datetime.datetime.now().astimezone().utcoffset()
        if offset is not None:
            hours = int(offset.total_seconds() // 3600)
            return _UTC_OFFSET_TO_IANA.get(hours, f"Etc/GMT{-hours:+d}")
    except Exception:
        pass

    return "Asia/Tokyo"


class AgentBridge:
    """WebSocket server that bridges Gateway requests to LLM responses."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18790,
        provider_configs: dict | None = None,
        mcp_configs: dict | None = None,
        memory_config: dict | None = None,
        config: dict | None = None,
    ):
        self.host = host
        self.port = port
        self._config = config or {}
        self.llm_router = LLMRouter(provider_configs)
        self.memory = FileMemory()
        self.persona = Persona.from_yaml_file()
        self.self_improving = SelfImproving()
        self.tts = self._init_tts()
        self.asr = self._init_asr()
        self.rag_memory = self._init_rag_memory(memory_config or {})

        # MCP tool server management
        self.mcp_manager = McpServerManager()
        mcp_configs = mcp_configs or {}
        if mcp_configs.get("servers"):
            self.mcp_manager.load_configs(mcp_configs["servers"])

        # Pending scheduler request futures (session_id -> asyncio.Future)
        self._scheduler_pending: dict[str, asyncio.Future] = {}

        # Active WebSocket reference (for autonomous proactive messaging)
        self._active_ws = None

        # Startup self-check info (populated in start())
        self._self_check_info: str = ""

        # Autonomous consciousness loop (initialized in start())
        self.autonomous: AutonomousManager | None = None

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

    @staticmethod
    def _build_env_context() -> str:
        """Build environment context string for the LLM (timezone, locale, etc.)."""
        import datetime

        parts = []

        # Detect IANA timezone name reliably
        iana_tz = _detect_iana_timezone()
        parts.append(f"- User timezone: {iana_tz}")

        # Current date/time for context
        now = datetime.datetime.now()
        parts.append(f"- Current date: {now.strftime('%Y-%m-%d %H:%M')}")

        return "\n\n## Environment\n" + "\n".join(parts) + "\n"

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

    @staticmethod
    def _init_rag_memory(memory_config: dict):
        """Initialize ChromaDB-backed long-term memory, if available."""
        if not _HAS_RAG:
            logger.info("RagMemory disabled: chromadb/sentence-transformers not installed")
            return None
        try:
            return RagMemory(
                db_path=memory_config.get("chromadb_path", "./data/chromadb"),
                embedding_model=memory_config.get(
                    "embedding_model",
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                ),
                finetune_candidates_path=memory_config.get(
                    "finetune_candidates_path", "./data/finetune_candidates"
                ),
            )
        except Exception as e:
            logger.error(f"Failed to initialize RagMemory: {e}")
            return None

    async def handle_connection(self, websocket: websockets.WebSocketServerProtocol):
        """Handle a single Gateway connection.

        Long-running handlers (_handle_chat, _handle_scheduler_trigger,
        _handle_audio_input) are spawned as independent tasks so the
        message loop keeps receiving incoming messages.  This is critical
        for scheduler_response messages: the Agent sends a
        scheduler_request *inside* _handle_chat and waits for the
        Gateway's scheduler_response — which arrives on the same
        WebSocket.  If _handle_chat were awaited inline, the async-for
        loop would never yield to receive the response, causing a
        deadlock (5 s timeout).
        """
        logger.info("Gateway connected")
        self._active_ws = websocket
        # Track spawned tasks so we can clean up on disconnect
        active_tasks: set[asyncio.Task] = set()

        def _on_task_done(task: asyncio.Task):
            active_tasks.discard(task)
            if not task.cancelled() and task.exception() is not None:
                logger.error(
                    f"Background handler error: {task.exception()}"
                )

        try:
            async for raw_message in websocket:
                session_id = ""
                try:
                    message = json.loads(raw_message)
                    session_id = message.get("session_id", "")
                    msg_type = message.get("type", "")

                    if msg_type == "chat":
                        task = asyncio.create_task(
                            self._handle_chat(websocket, message)
                        )
                        active_tasks.add(task)
                        task.add_done_callback(_on_task_done)
                    elif msg_type == "audio_input":
                        task = asyncio.create_task(
                            self._handle_audio_input(websocket, message)
                        )
                        active_tasks.add(task)
                        task.add_done_callback(_on_task_done)
                    elif msg_type == "scheduler_trigger":
                        task = asyncio.create_task(
                            self._handle_scheduler_trigger(websocket, message)
                        )
                        active_tasks.add(task)
                        task.add_done_callback(_on_task_done)
                    elif msg_type == "scheduler_response":
                        self._handle_scheduler_response(message)
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
                        "session_id": session_id,
                        "content": str(e),
                    }))

        except websockets.exceptions.ConnectionClosed:
            logger.info("Gateway disconnected")
        finally:
            self._active_ws = None
            # Cancel any still-running handlers on disconnect
            for task in active_tasks:
                task.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)

    async def _handle_chat(self, websocket, message: dict):
        """Process a chat request, execute MCP tools if needed, stream response."""
        session_id = message.get("session_id", "")
        text = message.get("text", "")
        permission = message.get("permission", "Public")
        channel = message.get("channel", "telegram")
        system_prompt = message.get("system_prompt") or self.persona.system_prompt(channel)

        try:
            learnings = await self.self_improving.load_learnings()
            if learnings:
                system_prompt += "\n" + learnings
        except Exception as e:
            logger.warning(f"Failed to load learnings: {e}")

        logger.info(
            f"Chat request: session={session_id}, "
            f"channel={channel}, permission={permission}"
        )

        # Load conversation history for context
        history = await self.memory.get_history(session_id)

        # Persist the user message
        if text:
            await self.memory.add_message(session_id, "user", text)

        # Collect MCP tools if permission allows
        mcp_tools: list[dict] = []
        if permission != "Public" and self.mcp_manager.configs:
            mcp_tools = await self.mcp_manager.list_all_tools()
            logger.info(
                f"MCP tools available: {len(mcp_tools)} tools, "
                f"sessions={list(self.mcp_manager._sessions.keys())}, "
                f"permission={permission}"
            )
        else:
            logger.info(
                f"MCP tools skipped: permission={permission}, "
                f"configs_loaded={bool(self.mcp_manager.configs)}"
            )

        # Add pseudo-tools for Authenticated+ users
        if permission != "Public":
            mcp_tools = mcp_tools + SCHEDULER_TOOLS
            if self.rag_memory:
                mcp_tools = mcp_tools + MEMORY_TOOLS

        # Inject startup self-check info
        if self._self_check_info:
            system_prompt += "\n" + self._self_check_info

        # Auto-inject related long-term memories (RAG)
        rag_context = ""
        if self.rag_memory and text:
            try:
                rag_results = await self.rag_memory.search(
                    query=text,
                    limit=5,
                    min_importance=2,
                )
                if rag_results:
                    lines = ["", "【関連する記憶】"]
                    for r in rag_results:
                        stars = "*" * r["importance"]
                        lines.append(
                            f"- [{r['category']}/{stars}] "
                            f"{r['content']} ({r['timestamp'][:10]})"
                        )
                    rag_context = "\n".join(lines) + "\n"
            except Exception as e:
                logger.warning(f"RAG search failed: {e}")

        # Add user environment context
        env_context = self._build_env_context()

        # Inject recent autonomous thinking summary
        thinking_context = ""
        if self.autonomous and self.autonomous.last_thinking_summary:
            thinking_context = (
                "\n\n【直近の自主思考メモ】\n"
                "以下はあなたが最近の自主思考時間に行った活動の記録です。\n"
                f"{self.autonomous.last_thinking_summary}\n"
            )

        # Decide tool passing strategy: native FC or prompt-based
        use_native_tools = self.llm_router.supports_native_tools()
        if mcp_tools and not use_native_tools:
            tool_prompt = build_tool_prompt(mcp_tools)
            tools_for_api = None
        else:
            tool_prompt = ""
            tools_for_api = mcp_tools if mcp_tools else None

        full_system = system_prompt + rag_context + thinking_context + env_context + tool_prompt

        # LLM generation with tool execution loop (max 3 iterations)
        full_response = ""
        current_text = text
        current_attachments = message.get("attachments", [])

        for _iteration in range(3):
            iteration_response = ""
            tool_call_request = None

            async for chunk in self.llm_router.generate(
                text=current_text,
                session_id=session_id,
                permission=permission,
                attachments=current_attachments,
                system_prompt=full_system,
                history=history,
                tools=tools_for_api,
            ):
                # Handle native function calling (GenerateChunk with tool_call)
                if hasattr(chunk, "tool_call") and chunk.tool_call is not None:
                    tool_call_request = chunk.tool_call
                    continue

                # Handle text chunk (str or GenerateChunk with text)
                text_content = chunk
                if hasattr(chunk, "text"):
                    text_content = chunk.text or ""

                if text_content:
                    iteration_response += text_content
                    # Stream immediately only for native-tool providers;
                    # non-native providers buffer for cleaning before send
                    if use_native_tools:
                        await websocket.send(json.dumps({
                            "type": "text_chunk",
                            "session_id": session_id,
                            "content": text_content,
                        }))

            # Determine tool call: native FC or prompt-based fallback
            tool_name = ""
            tool_args: dict = {}

            if tool_call_request is not None:
                # Native function calling — structured tool call from LLM
                tool_name = tool_call_request.name
                tool_args = tool_call_request.arguments
                logger.info(f"Native tool call: {tool_name}({tool_args})")
            elif not use_native_tools:
                # Prompt-based fallback — parse JSON from buffered text
                from .providers.openai_provider import _strip_internal_tags
                iteration_response = _strip_internal_tags(iteration_response)

                parsed = parse_tool_call(iteration_response)
                if parsed is not None:
                    tool_name = parsed.get("tool", "")
                    tool_args = parsed.get("arguments", {})
                    logger.info(f"Prompt-based tool call: {tool_name}({tool_args})")
                else:
                    # No tool call — send cleaned response to user
                    if iteration_response:
                        await websocket.send(json.dumps({
                            "type": "text_chunk",
                            "session_id": session_id,
                            "content": iteration_response,
                        }))
                    full_response += iteration_response
                    break
            else:
                # Native provider, no tool call
                full_response += iteration_response
                break

            # Tool call detected — don't add raw JSON to full_response

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

            # Execute tool: pseudo-tools are intercepted, others go to MCP
            if is_scheduler_tool(tool_name):
                logger.info(f"Executing scheduler tool: {tool_name}({tool_args})")
                tool_result = await self._execute_scheduler_tool(
                    websocket, tool_name, tool_args, session_id, channel, message
                )
                logger.info(f"Scheduler tool result: {tool_result[:200]}")
            elif is_memory_tool(tool_name):
                logger.info(f"Executing memory tool: {tool_name}({tool_args})")
                tool_result = await self._execute_memory_tool(
                    tool_name, tool_args
                )
                logger.info(f"Memory tool result: {tool_result[:200]}")
            else:
                logger.info(f"Executing MCP tool: {tool_name}({tool_args})")
                try:
                    tool_result = await self.mcp_manager.call_tool(
                        tool_name, tool_args
                    )
                except Exception as e:
                    logger.error(
                        f"MCP tool execution failed: {tool_name}: {e}"
                    )
                    tool_result = (
                        f"Error: Tool '{tool_name}' execution failed: {e}"
                    )
                    try:
                        err_entry = LearningEntry(
                            entry_type="ERR",
                            priority="medium",
                            area="mcp",
                            source="agent-runtime",
                            summary=f"MCP tool '{tool_name}' failed: {str(e)[:100]}",
                            details="",
                            action="",
                            pattern_key=f"mcp-fail-{tool_name}",
                            permission=permission,
                        )
                        err_id = await self.self_improving.log_learning(err_entry)
                        if err_id:
                            await self.self_improving.auto_promote(err_entry, err_id)
                    except Exception as si_err:
                        logger.warning(f"Failed to log tool error: {si_err}")
                logger.info(f"Tool result: {tool_result[:200]}")

            # Feed tool result back as next iteration's input
            if tool_call_request is not None and tool_call_request.call_id:
                # Native FC: use proper OpenAI tool protocol so the model
                # sees a coherent tool-call chain and can continue calling.
                history.append({
                    "role": "assistant",
                    "tool_calls": [{
                        "id": tool_call_request.call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args),
                        },
                    }],
                })
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call_request.call_id,
                    "content": tool_result,
                })
            else:
                # Prompt-based fallback: plain text
                if iteration_response:
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

        try:
            if text and full_response and permission != "Public":
                if self.self_improving.detect_correction(text, full_response):
                    entry = LearningEntry(
                        entry_type="FBK",
                        priority="medium",
                        area="agent",
                        source="user-feedback",
                        summary=f"User correction: {text[:150]}",
                        details=f"Bot said: {full_response[:200]}",
                        action="",
                        permission=permission,
                    )
                    entry_id = await self.self_improving.log_learning(entry)
                    if entry_id:
                        await self.self_improving.auto_promote(entry, entry_id)
        except Exception as e:
            logger.warning(f"Self-improving correction detection failed: {e}")

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

    async def _execute_memory_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute a memory pseudo-tool against the local RagMemory."""
        if not self.rag_memory:
            return "Error: Long-term memory is not available."

        action = tool_name.removeprefix("memory_")
        try:
            if action == "save":
                mem_id = await self.rag_memory.save(
                    content=tool_args["content"],
                    importance=tool_args.get("importance", 3),
                    category=tool_args.get("category", "conversation"),
                    tags=tool_args.get("tags"),
                )
                return f"記憶を保存しました (ID: {mem_id})"

            elif action == "search":
                results = await self.rag_memory.search(
                    query=tool_args["query"],
                    limit=tool_args.get("limit", 5),
                    min_importance=tool_args.get("min_importance", 1),
                    category=tool_args.get("category"),
                )
                if not results:
                    return "関連する記憶が見つかりませんでした。"
                lines = []
                for r in results:
                    stars = "*" * r["importance"]
                    lines.append(
                        f"- [{r['id']}] {stars} {r['content']} "
                        f"({r['category']}, {r['timestamp'][:10]})"
                    )
                return "検索結果:\n" + "\n".join(lines)

            elif action == "classify":
                ok = await self.rag_memory.classify(
                    memory_id=tool_args["memory_id"],
                    importance=tool_args.get("importance"),
                    category=tool_args.get("category"),
                    tags=tool_args.get("tags"),
                )
                return "記憶を更新しました。" if ok else "記憶IDが見つかりません。"

            elif action == "forget":
                ok = await self.rag_memory.forget(
                    memory_id=tool_args["memory_id"],
                    reason=tool_args.get("reason", ""),
                )
                return "記憶をアーカイブしました。" if ok else "記憶IDが見つかりません。"

            elif action == "promote":
                result = await self.rag_memory.promote(
                    memory_id=tool_args["memory_id"],
                    reason=tool_args.get("reason", ""),
                )
                if "error" in result:
                    return f"記憶IDが見つかりません: {result['error']}"
                return (
                    f"魂の記憶候補にマークしました。"
                    f"次回の微調整でモデルに刻まれます。(ID: {result['id']})"
                )

            elif action == "reflect":
                results = await self.rag_memory.reflect(
                    limit=tool_args.get("limit", 20),
                )
                if not results:
                    return "記憶がまだありません。"
                lines = []
                for r in results:
                    stars = "*" * r["importance"]
                    lines.append(f"- [{r['id']}] {stars} {r['content']}")
                return f"最近の記憶 ({len(results)}件):\n" + "\n".join(lines)

            elif action == "stats":
                s = await self.rag_memory.stats()
                return (
                    f"記憶統計: 総数={s['total']}, "
                    f"アーカイブ={s['archived']}, "
                    f"カテゴリ別={s['by_category']}, "
                    f"重要度別={s['by_importance']}, "
                    f"最新={s['latest_timestamp']}"
                )

            else:
                return f"Error: Unknown memory action: {action}"

        except Exception as e:
            logger.error(f"Memory tool error: {e}")
            return f"Error: {e}"

    async def _execute_scheduler_tool(
        self,
        websocket,
        tool_name: str,
        tool_args: dict,
        session_id: str,
        channel: str,
        message: dict,
    ) -> str:
        """Execute a scheduler pseudo-tool by sending a request to the Gateway."""
        action = tool_name.removeprefix("scheduler_")

        # Map tool names to Gateway action verbs
        action_map = {
            "create_job": "create",
            "list_jobs": "list",
            "delete_job": "delete",
        }
        gateway_action = action_map.get(action, action)

        # Build the request envelope
        request: dict = {
            "type": "scheduler_request",
            "session_id": session_id,
            "action": gateway_action,
        }

        if gateway_action == "create":
            # Extract target_id from session_id (e.g., "tg:12345" -> "12345")
            target_id = (
                session_id.split(":", 1)[-1] if ":" in session_id else session_id
            )
            channel_name = channel.lower() if channel else "telegram"

            # Determine one_shot default: true for delay, false for cron
            has_cron = "cron" in tool_args
            one_shot = tool_args.get("one_shot", not has_cron)

            # Auto-detect timezone if not specified
            timezone = tool_args.get("timezone", _detect_iana_timezone())

            request["job"] = {
                "name": tool_args.get("message", "unnamed")[:50],
                "message": tool_args.get("message", ""),
                "channel": channel_name,
                "target_id": target_id,
                "one_shot": one_shot,
                "timezone": timezone,
            }

            if "delay_seconds" in tool_args:
                request["job"]["delay_seconds"] = tool_args["delay_seconds"]
            elif "cron" in tool_args:
                request["job"]["cron"] = tool_args["cron"]
            elif "interval_secs" in tool_args:
                request["job"]["interval_secs"] = tool_args["interval_secs"]

        elif gateway_action == "delete":
            request["job_id"] = tool_args.get("job_id", "")

        # Send to Gateway and wait for response
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._scheduler_pending[session_id] = future

        await websocket.send(json.dumps(request))
        logger.info(f"Scheduler request sent: {gateway_action} for session {session_id}")

        try:
            response = await asyncio.wait_for(future, timeout=5.0)
        except asyncio.TimeoutError:
            return "Error: Scheduler request timed out"
        finally:
            self._scheduler_pending.pop(session_id, None)

        # Format response for LLM consumption
        if response.get("success"):
            if gateway_action == "create":
                return (
                    f"Job created successfully. "
                    f"Job ID: {response.get('job_id', 'unknown')}"
                )
            elif gateway_action == "list":
                jobs = response.get("jobs", [])
                if not jobs:
                    return "No active jobs/reminders found."
                lines = ["Active jobs:"]
                for j in jobs:
                    lines.append(
                        f"- [{j.get('id', '?')}] "
                        f"{j.get('name', '?')}: {j.get('message', '?')}"
                    )
                return "\n".join(lines)
            elif gateway_action == "delete":
                return f"Job {response.get('job_id', '')} deleted successfully."
            return "Success"
        else:
            return f"Error: {response.get('error', 'Unknown error')}"

    def _handle_scheduler_response(self, message: dict):
        """Route a scheduler_response from Gateway to the waiting future."""
        session_id = message.get("session_id", "")
        future = self._scheduler_pending.get(session_id)
        if future and not future.done():
            future.set_result(message)
        else:
            logger.warning(
                f"No pending scheduler request for session {session_id}"
            )

    async def _handle_scheduler_trigger(self, websocket, message: dict):
        """Handle a scheduler trigger (reminder/heartbeat fired by Gateway)."""
        session_id = message.get("session_id", "")
        trigger_type = message.get("trigger_type", "")
        job_message = message.get("message", "")

        logger.info(
            f"Scheduler trigger: type={trigger_type}, "
            f"session={session_id}, message={job_message[:100]}"
        )

        # Build a prompt for the LLM based on trigger type
        if trigger_type == "heartbeat":
            # Read HEARTBEAT.md checklist
            heartbeat_content = ""
            try:
                import os

                hb_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "workspace",
                    "HEARTBEAT.md",
                )
                if os.path.exists(hb_path):
                    with open(hb_path, "r", encoding="utf-8") as f:
                        heartbeat_content = f.read()
            except Exception as e:
                logger.warning(f"Failed to read HEARTBEAT.md: {e}")

            prompt = (
                f"[定期チェック]\n"
                f"定期ハートビートチェックを実行中。\n"
                f"{heartbeat_content}\n"
                f"特に問題がなければ、正確に「HEARTBEAT_OK」とだけ返答。\n"
                f"先生に伝えるべきことがあれば、簡潔な通知を作成。"
            )
        else:
            # Reminder or recurring job trigger
            prompt = (
                f"[リマインダー発火]\n"
                f"先生が設定したリマインダーが発火しました。\n"
                f"内容：「{job_message}」\n\n"
                f"先生に自然で親しみのあるリマインダーメッセージを送ってください。"
            )

        # Use the system prompt from the trigger's channel
        channel = message.get("channel", "telegram")
        system_prompt = (
            message.get("system_prompt") or self.persona.system_prompt(channel)
        )

        try:
            learnings = await self.self_improving.load_learnings()
            if learnings:
                system_prompt += "\n" + learnings
        except Exception as e:
            logger.warning(f"Failed to load learnings: {e}")

        # Add environment context
        env_context = self._build_env_context()
        full_system = system_prompt + env_context

        # Load conversation history for context
        history = await self.memory.get_history(session_id)

        # Generate response via LLM — buffer all chunks for cleaning
        full_response = ""
        async for chunk in self.llm_router.generate(
            text=prompt,
            session_id=session_id,
            permission="Admin",
            system_prompt=full_system,
            history=history,
        ):
            text_content = chunk
            if hasattr(chunk, "text"):
                text_content = chunk.text or ""
            if text_content:
                full_response += text_content

        # Clean thinking artifacts before sending
        from .providers.openai_provider import _strip_internal_tags
        full_response = _strip_internal_tags(full_response)

        if full_response:
            await websocket.send(json.dumps({
                "type": "text_chunk",
                "session_id": session_id,
                "content": full_response,
            }))

        # Signal completion
        await websocket.send(
            json.dumps({"type": "done", "session_id": session_id})
        )

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

    async def _send_proactive(
        self, channel: str, target_id: str, message: str
    ):
        """Send a proactive message via Gateway's scheduler (one-shot job)."""
        ws = self._active_ws
        if ws is None:
            logger.warning("No active WebSocket, cannot send proactive message")
            return

        session_id = f"{channel}:{target_id}"
        request = {
            "type": "scheduler_request",
            "session_id": session_id,
            "action": "create",
            "job": {
                "name": "autonomous_message",
                "message": message,
                "channel": channel,
                "target_id": target_id,
                "one_shot": True,
                "delay_seconds": 1,
                "timezone": "Asia/Tokyo",
            },
        }
        await ws.send(json.dumps(request))
        logger.info(f"Proactive message queued: {message[:80]}")

    async def start(self):
        """Start the WebSocket bridge server."""
        logger.info(f"Agent bridge starting on ws://{self.host}:{self.port}")

        # Connect to MCP servers before accepting gateway connections
        if self.mcp_manager.configs:
            logger.info(f"Connecting to {len(self.mcp_manager.configs)} MCP server(s)...")
            await self.mcp_manager.connect_all()
            tools = await self.mcp_manager.list_all_tools()
            logger.info(f"MCP ready: {len(tools)} tool(s) available")

        # Run startup self-check
        startup_cfg = self._config.get("startup", {})
        if startup_cfg.get("self_check_enabled", False):
            inference_url = startup_cfg.get(
                "inference_url", "http://127.0.0.1:18800/v1"
            )
            try:
                self._self_check_info = await startup_self_check(
                    inference_url, self.rag_memory
                )
            except Exception as e:
                logger.warning(f"Startup self-check failed: {e}")

        # Initialize autonomous consciousness loop
        auto_cfg = self._config.get("scheduler", {}).get("autonomous", {})
        if auto_cfg.get("enabled", False):
            self.autonomous = AutonomousManager(
                config=auto_cfg,
                llm_router=self.llm_router,
                rag_memory=self.rag_memory,
                persona=self.persona,
                send_message_callback=self._send_proactive,
                execute_memory_tool=self._execute_memory_tool,
            )
            self.autonomous.start()

        try:
            async with websockets.serve(
                self.handle_connection,
                self.host,
                self.port,
            ):
                logger.info("Agent bridge ready")
                await asyncio.Future()  # Run forever
        finally:
            if self.autonomous:
                await self.autonomous.stop()
            await self.mcp_manager.shutdown()
