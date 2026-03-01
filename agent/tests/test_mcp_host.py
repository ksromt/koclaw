"""Tests for MCP server manager config parsing."""

from koclaw_agent.mcp_host.server_manager import McpServerConfig, McpServerManager


def test_server_config_from_dict():
    cfg = McpServerConfig.from_dict("time", {
        "command": "uvx",
        "args": ["mcp-server-time"],
    })
    assert cfg.name == "time"
    assert cfg.command == "uvx"
    assert cfg.args == ["mcp-server-time"]
    assert cfg.env == {}
    assert cfg.transport == "stdio"


def test_server_config_with_env():
    cfg = McpServerConfig.from_dict("github", {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "ghp_xxx"},
    })
    assert cfg.env == {"GITHUB_TOKEN": "ghp_xxx"}


def test_manager_registers_configs():
    manager = McpServerManager()
    configs = {
        "time": {"command": "uvx", "args": ["mcp-server-time"]},
        "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    }
    manager.load_configs(configs)
    assert len(manager.configs) == 2
    assert "time" in manager.configs
    assert "fs" in manager.configs


def test_manager_empty_configs():
    manager = McpServerManager()
    manager.load_configs({})
    assert len(manager.configs) == 0
