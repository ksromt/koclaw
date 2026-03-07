"""
Config loader — reads config.toml and resolves provider settings.

Resolution rules for API keys:
  - `api_key` field  → use directly
  - `api_key_env` field → read from os.environ[value]
  - neither → provider unavailable

Config file search order:
  1. KOCLAW_CONFIG env var
  2. ./config.toml (cwd)
  3. ../config.toml (parent, for running from agent/)
"""

import os
from pathlib import Path

from loguru import logger

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.10 fallback


def _find_config_path() -> Path | None:
    """Locate config.toml by searching known locations."""
    if env_path := os.environ.get("KOCLAW_CONFIG"):
        p = Path(env_path)
        if p.exists():
            return p

    for candidate in [Path("config.toml"), Path("../config.toml")]:
        if candidate.exists():
            return candidate.resolve()

    return None


def load_config() -> dict:
    """Load and return the full config dict from config.toml."""
    path = _find_config_path()
    if path is None:
        logger.warning("config.toml not found, falling back to environment variables only")
        return {}

    logger.info(f"Loading config from {path}")
    with open(path, "rb") as f:
        return tomllib.load(f)


def resolve_provider_configs(config: dict) -> dict[str, dict]:
    """Extract provider configs with resolved API keys.

    Returns a dict like:
      {"openai": {"api_key": "sk-...", "model": "gpt-4o", "base_url": None}, ...}
    """
    providers_section = config.get("providers", {})
    default_provider = providers_section.get("default", "anthropic")

    resolved = {"_default": default_provider}

    for name in ("anthropic", "openai", "deepseek", "ollama", "kokoron"):
        section = providers_section.get(name)
        if section is None:
            continue

        # Resolve API key: direct value > env var
        api_key = section.get("api_key")
        if not api_key:
            env_var = section.get("api_key_env")
            if env_var:
                api_key = os.environ.get(env_var)

        resolved[name] = {
            "api_key": api_key,
            "model": section.get("model"),
            "base_url": section.get("base_url"),
        }

    return resolved


def resolve_mcp_configs(config: dict) -> dict:
    """Extract MCP configuration including servers and permission settings.

    Expected config.toml format:
      [mcp]
      permission_mode = "blocklist"
      blocked_tools = ["shell_exec", "write_file"]

      [mcp.servers.time]
      command = "uvx"
      args = ["mcp-server-time"]

      [mcp.servers.filesystem]
      command = "npx"
      args = ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
      env = { ALLOWED_DIR = "/workspace" }
    """
    mcp_section = config.get("mcp", {})
    return {
        "servers": mcp_section.get("servers", {}),
        "permission_mode": mcp_section.get("permission_mode", "blocklist"),
        "blocked_tools": mcp_section.get("blocked_tools", []),
        "allowed_tools": mcp_section.get("allowed_tools", []),
    }
