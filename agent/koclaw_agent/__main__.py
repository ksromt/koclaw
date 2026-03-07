"""Entry point: python -m koclaw_agent"""

import asyncio

from loguru import logger

from .bridge import AgentBridge
from .config import load_config, resolve_mcp_configs, resolve_provider_configs


def main():
    logger.info("Koclaw Agent starting...")

    config = load_config()
    provider_configs = resolve_provider_configs(config)
    mcp_configs = resolve_mcp_configs(config)

    memory_config = config.get("memory", {})

    bridge = AgentBridge(
        host="0.0.0.0",
        port=18790,
        provider_configs=provider_configs,
        mcp_configs=mcp_configs,
        memory_config=memory_config,
    )

    asyncio.run(bridge.start())


if __name__ == "__main__":
    main()
