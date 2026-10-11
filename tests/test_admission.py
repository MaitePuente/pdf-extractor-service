import asyncio

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.worker import ExtractionWorker
from app.extractor import ExtractionResponse


def test_declared_oversize_rejected_before_receiving_body(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")

    async def exercise():
        received = 0
        messages = []

        async def receive():
            nonlocal received
            received += 1
            return {"type": "http.request", "body": b"%PDF", "more_body": False}

        async def send(message):
            messages.append(message)

        async with app.router.lifespan_context(app):
            await app({"type": "http", "method": "POST", "path": "/extract", "query_string": b"", "headers": [(b"content-type", b"application/pdf"), (b"content-length", b"1048577")], "server": ("test", 80), "client": ("test", 1), "scheme": "http", "http_version": "1.1"}, receive, send)
        assert messages[0]["status"] == 413
        assert received == 0

    asyncio.run(exercise())


def test_stream_without_content_length_obeys_limit(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")

    async def exercise():
        async def chunks():
            yield b"%PDF" + b"x" * (1024 * 1024)
            pytest.fail("Must stop consuming an oversized stream")

        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/extract", content=chunks(), headers={"Content-Type": "application/pdf"})
                assert response.status_code == 413

    asyncio.run(exercise())


@pytest.mark.parametrize("queue_size", [0, 1])
def test_full_or_expired_admission_returns_429_without_reading(monkeypatch, queue_size):
    monkeypatch.setenv("MAX_IN_FLIGHT", "1")
    monkeypatch.setenv("QUEUE_SIZE", str(queue_size))
    monkeypatch.setenv("ADMISSION_TIMEOUT_SECONDS", "0.02")

    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        async def convert(self, body, *, profile=None):
            started.set()
            await release.wait()
            return ExtractionResponse(content="ok", page_count=1)

        async def unread():
            pytest.fail("Admission must reject before reading bytes")
            yield b"%PDF"

        monkeypatch.setattr(ExtractionWorker, "extract", convert)
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
                first = asyncio.create_task(client.post("/extract", content=b"%PDF-a", headers={"Content-Type": "application/pdf"}))
                await started.wait()
                try:
                    response = await client.post("/extract", content=unread(), headers={"Content-Type": "application/pdf"})
                    assert response.status_code == 429
                    assert response.headers["content-type"] == "application/problem+json"
                    assert response.json()["request_id"] == response.headers["X-Request-ID"]
                    assert int(response.headers["Retry-After"]) >= 1
                finally:
                    release.set()
                    assert (await first).status_code == 200
                assert (await client.post("/extract", content=b"%PDF-b", headers={"Content-Type": "application/pdf"})).status_code == 200

    asyncio.run(exercise())
