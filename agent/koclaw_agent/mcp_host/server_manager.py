"""Manages MCP server lifecycle -- launch, connect, discover tools, invoke."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass
class McpServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    url: str | None = None

    @classmethod
    def from_dict(cls, name: str, d: dict) -> McpServerConfig:
        return cls(
            name=name,
            command=d.get("command", ""),
            args=d.get("args", []),
            env=d.get("env", {}),
            transport=d.get("transport", "stdio"),
            url=d.get("url"),
        )


class McpServerManager:
    """Manages multiple MCP server connections."""

    def __init__(self) -> None:
        self.configs: dict[str, McpServerConfig] = {}
        self._exit_stack: AsyncExitStack | None = None
        self._sessions: dict[str, ClientSession] = {}
        self._tool_map: dict[str, str] = {}

    def load_configs(self, configs: dict[str, dict]) -> None:
        """Load server configs from a dict (from config.toml [mcp.servers])."""
        self.configs.clear()
        for name, cfg_dict in configs.items():
            cfg = McpServerConfig.from_dict(name, cfg_dict)
            self.configs[name] = cfg
            logger.info("MCP server config loaded: {} ({})", name, cfg.command)

    async def connect_all(self) -> None:
        """Launch all configured MCP servers and establish sessions."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for name, cfg in self.configs.items():
            try:
                await self._connect_server(name, cfg)
            except Exception:
                logger.exception("Failed to connect MCP server: {}", name)

    async def _connect_server(self, name: str, cfg: McpServerConfig) -> None:
        """Launch a single MCP server subprocess and initialize the session."""
        if self._exit_stack is None:
            raise RuntimeError("connect_all() must be called before _connect_server()")

        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env or None,
        )
        reader, writer = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        session: ClientSession = await self._exit_stack.enter_async_context(
            ClientSession(reader, writer)
        )
        await session.initialize()
        self._sessions[name] = session
        logger.info("MCP server connected: {}", name)

        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            self._tool_map[tool.name] = name

    async def list_all_tools(self) -> list[dict]:
        """Collect tool definitions from every connected MCP server."""
        all_tools: list[dict] = []
        for name, session in self._sessions.items():
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                all_tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema,
                    "_mcp_server": name,
                })
        return all_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Invoke a tool by name, routing to the correct MCP server."""
        server_name = self._tool_map.get(tool_name)
        if not server_name:
            return f"Error: Unknown tool '{tool_name}'"

        session = self._sessions.get(server_name)
        if not session:
            return f"Error: Server '{server_name}' not connected"

        result = await session.call_tool(tool_name, arguments=arguments)
        texts = [
            content.text
            for content in result.content
            if hasattr(content, "text")
        ]
        return "\n".join(texts) if texts else str(result)

    async def shutdown(self) -> None:
        """Close all MCP server connections and clean up resources."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._sessions.clear()
            self._tool_map.clear()
