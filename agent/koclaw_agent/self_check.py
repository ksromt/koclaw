"""Startup self-check — queries inference server and memory stats."""

from datetime import datetime

import httpx
from loguru import logger


async def startup_self_check(
    inference_url: str,
    rag_memory,
) -> str:
    """Run startup diagnostics and return a formatted info block.

    The result is injected into the system prompt so Kokoron
    is aware of her own runtime environment.
    """
    now = datetime.now()
    lines = [f"【起動自検 — {now.strftime('%Y-%m-%d %H:%M:%S')} JST】"]

    # Check inference server
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{inference_url}/models")
            if resp.status_code == 200:
                data = resp.json()
                for m in data.get("data", []):
                    lines.append(f"- 推論モデル: {m.get('id', 'unknown')}")
            else:
                lines.append(f"- 推論サーバー: HTTP {resp.status_code}")
    except Exception as e:
        lines.append(f"- 推論サーバー: 接続失敗 ({type(e).__name__})")

    # Memory stats
    if rag_memory:
        try:
            stats = await rag_memory.stats()
            lines.append(
                f"- 長期記憶: {stats['total']}件 "
                f"(アーカイブ: {stats['archived']}件)"
            )
            if stats.get("latest_timestamp"):
                lines.append(f"- 最新記憶: {stats['latest_timestamp'][:16]}")
        except Exception as e:
            lines.append(f"- 長期記憶: エラー ({e})")
    else:
        lines.append("- 長期記憶: 無効")

    result = "\n".join(lines) + "\n"
    logger.info(f"Self-check complete:\n{result}")
    return result
