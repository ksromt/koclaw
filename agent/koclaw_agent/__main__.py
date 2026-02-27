"""Entry point: python -m koclaw_agent"""

import asyncio

from loguru import logger

from .bridge import AgentBridge


def main():
    logger.info("Koclaw Agent starting...")

    bridge = AgentBridge(
        host="127.0.0.1",
        port=18790,
    )

    asyncio.run(bridge.start())


if __name__ == "__main__":
    main()
