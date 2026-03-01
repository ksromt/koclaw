"""Tests for ClawHub API client."""
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from koclaw_agent.mcp_host.clawhub_client import ClawHubClient


def test_client_default_registry():
    client = ClawHubClient()
    assert "clawhub" in client.registry_url.lower()


def test_client_custom_registry():
    client = ClawHubClient(registry_url="https://my-registry.example.com")
    assert client.registry_url == "https://my-registry.example.com"


@pytest.mark.asyncio
async def test_search_returns_results():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"name": "web-search", "description": "Search the web", "version": "1.0.0", "slug": "web-search"},
            {"name": "code-gen", "description": "Generate code", "version": "2.1.0", "slug": "code-gen"},
        ]
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = ClawHubClient()
        results = await client.search("search")
        assert len(results) == 2
        assert results[0]["name"] == "web-search"


@pytest.mark.asyncio
async def test_search_empty_results():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = ClawHubClient()
        results = await client.search("nonexistent-skill-xyz")
        assert results == []
