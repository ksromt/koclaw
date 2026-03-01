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

    bridge = AgentBridge(
        host="127.0.0.1",
        port=18790,
        provider_configs=provider_configs,
        mcp_configs=mcp_configs,
    )

    asyncio.run(bridge.start())


if __name__ == "__main__":
    main()
