"""Client for the ClawHub skill registry."""
from __future__ import annotations

import shutil
from pathlib import Path

import httpx
from loguru import logger

DEFAULT_REGISTRY = "https://api.clawhub.ai/v1"
SKILLS_DIR = Path.home() / ".koclaw" / "skills"


class ClawHubClient:
    """HTTP client for the ClawHub skill registry API."""

    def __init__(self, registry_url: str = DEFAULT_REGISTRY) -> None:
        self.registry_url = registry_url

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.registry_url}/skills/search",
                params={"q": query, "limit": limit},
            )
            if resp.status_code != 200:
                logger.error("ClawHub search failed: %s", resp.status_code)
                return []
            data = resp.json()
            return data.get("results", [])

    async def inspect(self, slug: str) -> dict | None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.registry_url}/skills/{slug}")
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                logger.error("ClawHub inspect failed: %s", resp.status_code)
                return None
            return resp.json()

    def _validate_target(self, target: Path) -> bool:
        """Ensure the resolved target is within SKILLS_DIR to prevent path traversal."""
        try:
            resolved = target.resolve()
            return str(resolved).startswith(str(SKILLS_DIR.resolve()))
        except (OSError, ValueError):
            return False

    async def install(self, slug: str, target_dir: Path | None = None) -> bool:
        target = target_dir or SKILLS_DIR / slug
        if not self._validate_target(target):
            logger.error("Path traversal detected in slug: %s", slug)
            return False
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{self.registry_url}/skills/{slug}/download")
            if resp.status_code != 200:
                logger.error("ClawHub download failed for '%s': %s", slug, resp.status_code)
                return False
            data = resp.json()
            skill_md = data.get("skill_md", "")
            if not skill_md:
                logger.error("No SKILL.md content in download response")
                return False
            # Create directory only after successful download validation
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
            for filename, content in data.get("files", {}).items():
                safe_name = Path(filename).name
                (target / safe_name).write_text(content, encoding="utf-8")
            logger.info("Installed skill '%s' to %s", slug, target)
            return True

    async def uninstall(self, slug: str, target_dir: Path | None = None) -> bool:
        target = target_dir or SKILLS_DIR / slug
        if not self._validate_target(target):
            logger.error("Path traversal detected in slug: %s", slug)
            return False
        if target.is_dir():
            shutil.rmtree(target)
            logger.info("Uninstalled skill '%s'", slug)
            return True
        return False
