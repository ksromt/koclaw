"""Tests for MCP tool permission enforcement."""
from koclaw_agent.mcp_host.tool_permissions import ToolPermissionChecker


def test_admin_can_use_all_tools():
    checker = ToolPermissionChecker()
    assert checker.is_allowed("shell_exec", "Admin") is True
    assert checker.is_allowed("read_file", "Admin") is True


def test_authenticated_can_use_safe_tools():
    checker = ToolPermissionChecker()
    assert checker.is_allowed("web_search", "Authenticated") is True
    assert checker.is_allowed("get_time", "Authenticated") is True


def test_authenticated_blocked_from_dangerous_tools():
    checker = ToolPermissionChecker(
        blocked_for_authenticated=["shell_exec", "write_file", "delete_file"]
    )
    assert checker.is_allowed("shell_exec", "Authenticated") is False
    assert checker.is_allowed("delete_file", "Authenticated") is False


def test_public_blocked_from_all_tools():
    checker = ToolPermissionChecker()
    assert checker.is_allowed("web_search", "Public") is False
    assert checker.is_allowed("get_time", "Public") is False


def test_custom_allowlist():
    checker = ToolPermissionChecker(
        allowed_for_authenticated=["web_search", "get_time"]
    )
    assert checker.is_allowed("web_search", "Authenticated") is True
    assert checker.is_allowed("shell_exec", "Authenticated") is False
