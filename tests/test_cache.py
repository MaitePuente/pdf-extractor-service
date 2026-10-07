import asyncio
import hashlib
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.main import app
from app.worker import ExtractionWorker


class FakeRedis:
    """Small in-memory substitute at the Redis network boundary."""

    def __init__(self):
        self.values = {}
        self.reads = []
        self.writes = []
        self.closed = False
        self.pings = 0

    async def ping(self):
        self.pings += 1
        return True

    async def get(self, key):
        self.reads.append(key)
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        self.values[key] = value
        self.writes.append((key, value, ex))

    async def aclose(self):
        self.closed = True


@pytest.fixture
def redis_cache(monkeypatch):
    backend = FakeRedis()
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: backend)
    return backend


def pdf_bytes(text="Cache example"):
    with pymupdf.open() as document:
        for number in (1, 2):
            page = document.new_page()
            page.insert_text((72, 100), f"{text} page {number}")
        return document.tobytes()


def post_pdf(client, body):
    return client.post("/extract", content=body, headers={"Content-Type": "application/pdf"})


def test_same_pdf_is_miss_then_hit_without_reconverting(redis_cache, monkeypatch):
    body = pdf_bytes()
    with TestClient(app) as client:
        first = post_pdf(client, body)
        assert first.status_code == 200
        assert first.headers.get("X-Cache") == "MISS"

        async def conversion_must_not_run(*args, **kwargs):
            pytest.fail("A cache hit must not convert the PDF again")

        # The CPU process is the conversion boundary. Patching a converter in
        # the parent cannot intercept a spawned child's imported functions.
        monkeypatch.setattr(ExtractionWorker, "extract", conversion_must_not_run)
        second = post_pdf(client, body)

    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert set(second.json()) == {"content", "page_count"}
    assert second.json()["page_count"] == 2
    assert "Cache example page 1" in second.json()["content"]


@pytest.mark.parametrize("namespace", ["v1", "v2", "v3"])
def test_previous_markdown_output_is_not_reused_by_new_engine(redis_cache, namespace):
    body = pdf_bytes()
    old_key = f"extract:{namespace}:" + hashlib.sha256(body).hexdigest()
    redis_cache.values[old_key] = json.dumps({"content": "Previous engine output", "page_count": 2})
    with TestClient(app) as client:
        response = post_pdf(client, body)
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert "Cache example page 1" in response.json()["content"]
    assert old_key in redis_cache.values  # Preserve data from the previous phase.


def test_redis_connection_is_warmed_once_at_startup(redis_cache):
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert redis_cache.pings == 1
        body = pdf_bytes()
        assert post_pdf(client, body).headers["X-Cache"] == "MISS"
        assert post_pdf(client, body).headers["X-Cache"] == "HIT"
        assert redis_cache.pings == 1


@pytest.mark.parametrize("failure", ["connection", "timeout"])
def test_failed_startup_ping_keeps_service_available(redis_cache, monkeypatch, caplog, failure):
    async def unavailable():
        if failure == "connection":
            raise RedisConnectionError("Warm-up unavailable")
        await asyncio.sleep(0.1)

    monkeypatch.setenv("CACHE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(redis_cache, "ping", unavailable)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = post_pdf(client, pdf_bytes())
    assert response.status_code == 200
    assert response.json()["page_count"] == 2
    assert "operation=warmup" in caplog.text


def test_disabled_cache_never_constructs_redis(monkeypatch):
    def must_not_connect(*args, **kwargs):
        pytest.fail("Disabled cache must not construct a Redis client")

    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setattr(Redis, "from_url", must_not_connect)
    with TestClient(app) as client:
        response = post_pdf(client, pdf_bytes())

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "BYPASS"
    assert response.json()["page_count"] == 2


@pytest.mark.parametrize("operation", ["get", "set"])
def test_redis_failure_is_fail_open(redis_cache, monkeypatch, caplog, operation):
    async def unavailable(*args, **kwargs):
        raise RedisConnectionError("Redis is unavailable")

    monkeypatch.setattr(redis_cache, operation, unavailable)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "service": "extractor"}
        response = post_pdf(client, pdf_bytes())

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "ERROR"
    assert response.json()["page_count"] == 2
    assert "Cache example" in response.json()["content"]
    assert any(r.levelname == "WARNING" and "CACHE ERROR" in r.message for r in caplog.records)


@pytest.mark.parametrize("operation", ["get", "set"])
def test_slow_cache_has_a_deadline(redis_cache, monkeypatch, caplog, operation):
    original = getattr(redis_cache, operation)

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.1)
        return await original(*args, **kwargs)

    monkeypatch.setenv("CACHE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(redis_cache, operation, slow)
    with TestClient(app) as client:
        response = post_pdf(client, pdf_bytes())

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "ERROR"
    assert "TimeoutError" in caplog.text


@pytest.mark.parametrize("value", [b"not json", b'{}', b'{"content":42,"page_count":2}'])
def test_invalid_cached_value_is_ignored(redis_cache, caplog, value):
    body = pdf_bytes()
    redis_cache.values["extract:v4:" + hashlib.sha256(body).hexdigest()] = value
    with TestClient(app) as client:
        response = post_pdf(client, body)

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "ERROR"
    assert response.json()["page_count"] == 2
    assert "Cache example" in response.json()["content"]
    assert "CACHE ERROR" in caplog.text


def test_invalid_redis_url_does_not_prevent_startup(monkeypatch, caplog):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "invalid-scheme://cache")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = post_pdf(client, pdf_bytes())

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "ERROR"
    assert "CACHE ERROR" in caplog.text


def test_different_pdfs_have_sha256_keys_and_configured_ttl(redis_cache, monkeypatch):
    monkeypatch.setenv("CACHE_TTL_SECONDS", "47")
    first_body, second_body = pdf_bytes("First document"), pdf_bytes("Second document")
    with TestClient(app) as client:
        first = post_pdf(client, first_body)
        second = post_pdf(client, second_body)
        again = post_pdf(client, first_body)

    assert first.headers["X-Cache"] == second.headers["X-Cache"] == "MISS"
    assert again.headers["X-Cache"] == "HIT"
    assert again.json() == first.json()
    assert first.json() != second.json()
    assert set(redis_cache.values) == {
        "extract:v4:" + hashlib.sha256(body).hexdigest()
        for body in (first_body, second_body)
    }
    assert [write[2] for write in redis_cache.writes] == [47, 47]
    assert json.loads(redis_cache.writes[0][1]) == first.json()
    assert redis_cache.closed


@pytest.mark.parametrize("body,content_type,status", [
    (b"", "application/pdf", 400),
    (b"not PDF", "application/pdf", 400),
    (b"%PDF-1.7\ninvalid", "application/pdf", 400),
    (b"%PDF", "text/plain", 415),
])
def test_invalid_requests_are_not_cached(redis_cache, body, content_type, status):
    with TestClient(app) as client:
        response = client.post("/extract", content=body, headers={"Content-Type": content_type})

    assert response.status_code == status
    assert not redis_cache.writes
    if not body.startswith(b"%PDF") or content_type != "application/pdf":
        assert not redis_cache.reads


def test_redis_close_failure_does_not_break_shutdown(redis_cache, monkeypatch, caplog):
    async def close_failure():
        raise RedisConnectionError("Connection lost during shutdown")

    monkeypatch.setattr(redis_cache, "aclose", close_failure)
    with TestClient(app) as client:
        assert post_pdf(client, pdf_bytes()).status_code == 200

    assert "operation=close" in caplog.text
