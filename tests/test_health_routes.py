from fastapi.testclient import TestClient
import pytest
import asyncio

from app.main import app


def test_live_is_independent_of_redis(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("CACHE_TIMEOUT_SECONDS", "0.01")
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "pdf-extractor"}


@pytest.mark.parametrize("required,expected", [(False, 200), (True, 503)])
def test_ready_reports_redis_outage_with_configured_policy(monkeypatch, required, expected):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("CACHE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("READINESS_REDIS_REQUIRED", str(required))
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == expected
    assert response.json() == {"status": "degraded", "dependencies": {"redis": "unavailable"}}


def test_ready_reports_healthy_redis(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("CACHE_TIMEOUT_SECONDS", "0.01")

    class RedisProbe:
        async def ping(self):
            return True

        async def aclose(self):
            pass

    with TestClient(app) as client:
        app.state.cache.client = RedisProbe()
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"redis": "ok"}}


def test_ready_probe_has_short_timeout(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("CACHE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("READINESS_TIMEOUT_SECONDS", "0.01")

    class SlowRedis:
        async def ping(self):
            await asyncio.sleep(1)

        async def aclose(self):
            pass

    with TestClient(app) as client:
        app.state.cache.client = SlowRedis()
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["dependencies"]["redis"] == "unavailable"
