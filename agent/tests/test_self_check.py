"""Tests for startup self-check module."""

import pytest

from koclaw_agent.self_check import startup_self_check


class FakeRagMemory:
    """Minimal RagMemory mock for self-check tests."""

    def __init__(self, stats_data=None, error=False):
        self._stats_data = stats_data or {
            "total": 42,
            "archived": 3,
            "latest_timestamp": "2026-03-08T12:00:00",
        }
        self._error = error

    async def stats(self):
        if self._error:
            raise RuntimeError("DB connection failed")
        return self._stats_data


class FakeHTTPResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data


@pytest.fixture
def mock_httpx_ok(monkeypatch):
    """Patch httpx.AsyncClient to return a successful /models response."""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return FakeHTTPResponse(200, {
                "data": [{"id": "kokoron-v1"}, {"id": "kokoron-v2"}]
            })

    import koclaw_agent.self_check as sc
    monkeypatch.setattr(sc, "httpx", type("httpx", (), {
        "AsyncClient": lambda **kw: FakeClient(),
    }))


@pytest.fixture
def mock_httpx_fail(monkeypatch):
    """Patch httpx.AsyncClient to simulate connection failure."""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            raise ConnectionError("refused")

    import koclaw_agent.self_check as sc
    monkeypatch.setattr(sc, "httpx", type("httpx", (), {
        "AsyncClient": lambda **kw: FakeClient(),
    }))


@pytest.fixture
def mock_httpx_500(monkeypatch):
    """Patch httpx.AsyncClient to return HTTP 500."""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return FakeHTTPResponse(500, {})

    import koclaw_agent.self_check as sc
    monkeypatch.setattr(sc, "httpx", type("httpx", (), {
        "AsyncClient": lambda **kw: FakeClient(),
    }))


# ── Happy path ──


async def test_self_check_full(mock_httpx_ok):
    result = await startup_self_check(
        "http://127.0.0.1:18800/v1", FakeRagMemory()
    )
    assert "起動自検" in result
    assert "kokoron-v1" in result
    assert "kokoron-v2" in result
    assert "42" in result
    assert "アーカイブ: 3" in result


async def test_self_check_models_listed(mock_httpx_ok):
    result = await startup_self_check(
        "http://localhost:8000/v1", FakeRagMemory()
    )
    assert result.count("推論モデル") == 2


# ── Inference server errors ──


async def test_self_check_inference_connection_fail(mock_httpx_fail):
    result = await startup_self_check(
        "http://127.0.0.1:18800/v1", FakeRagMemory()
    )
    assert "接続失敗" in result
    assert "ConnectionError" in result
    # Memory stats should still work
    assert "42" in result


async def test_self_check_inference_http_error(mock_httpx_500):
    result = await startup_self_check(
        "http://127.0.0.1:18800/v1", FakeRagMemory()
    )
    assert "HTTP 500" in result


# ── Memory variations ──


async def test_self_check_no_rag(mock_httpx_ok):
    result = await startup_self_check(
        "http://127.0.0.1:18800/v1", None
    )
    assert "長期記憶: 無効" in result
    assert "kokoron-v1" in result


async def test_self_check_rag_error(mock_httpx_ok):
    result = await startup_self_check(
        "http://127.0.0.1:18800/v1", FakeRagMemory(error=True)
    )
    assert "エラー" in result


async def test_self_check_no_latest_timestamp(mock_httpx_ok):
    mem = FakeRagMemory(stats_data={
        "total": 0,
        "archived": 0,
        "latest_timestamp": None,
    })
    result = await startup_self_check(
        "http://127.0.0.1:18800/v1", mem
    )
    assert "総数=0" not in result  # stats format is different
    assert "0件" in result
    assert "最新記憶" not in result


async def test_self_check_with_latest_timestamp(mock_httpx_ok):
    mem = FakeRagMemory(stats_data={
        "total": 10,
        "archived": 2,
        "latest_timestamp": "2026-03-08T15:30:00",
    })
    result = await startup_self_check(
        "http://127.0.0.1:18800/v1", mem
    )
    assert "10件" in result
    assert "最新記憶: 2026-03-08T15:30" in result
