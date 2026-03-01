"""Permission enforcement for MCP tool invocations.

Extends Koclaw's three-tier permission model to MCP tools:
| Permission    | Tool Access                              |
|---------------|------------------------------------------|
| Public        | NO tools (chat only)                     |
| Authenticated | Safe tools only (configurable allowlist) |
| Admin         | All tools (unrestricted)                 |
"""
from __future__ import annotations

from loguru import logger


class ToolPermissionChecker:
    """Check whether a tool invocation is allowed for a given permission level."""

    def __init__(
        self,
        allowed_for_authenticated: list[str] | None = None,
        blocked_for_authenticated: list[str] | None = None,
    ) -> None:
        self._allowlist = allowed_for_authenticated
        self._blocklist = blocked_for_authenticated or []

    def is_allowed(self, tool_name: str, permission: str) -> bool:
        if permission == "Admin":
            return True
        if permission == "Public":
            return False
        if permission == "Authenticated":
            if self._allowlist is not None:
                return tool_name in self._allowlist
            return tool_name not in self._blocklist
        logger.warning("Unknown permission level: %s", permission)
        return False
