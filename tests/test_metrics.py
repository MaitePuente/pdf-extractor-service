import asyncio

import httpx2
from fastapi.testclient import TestClient

from app.main import create_app
from app.worker import ExtractionWorker
from app.extractor import ExtractionResponse


def test_metrics_disabled_has_no_endpoint_or_registry(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "false")
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/metrics").status_code == 404
    assert app.state.metrics is None


def test_metrics_endpoint_counts_requests_and_bounded_labels(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.post("/extract", content=b"not-pdf", headers={"Content-Type": "application/pdf", "X-Request-ID": "unique-secret"}).status_code == 400
        metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert 'pdf_http_requests_total{method="GET",route="/health/live",status="200"} 1.0' in metrics.text
    assert 'pdf_http_requests_total{method="POST",route="/extract",status="400"} 1.0' in metrics.text
    assert "pdf_http_request_duration_seconds_bucket" in metrics.text
    assert "pdf_request_body_receive_seconds_bucket" in metrics.text
    assert "pdf_cache_requests_total" in metrics.text
    assert "pdf_singleflight_shared_total" in metrics.text
    assert "unique-secret" not in metrics.text


def test_ten_identical_requests_count_one_real_worker_call_and_nine_shares(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    app = create_app()
    calls = []
    started, release = asyncio.Event(), asyncio.Event()

    async def convert(self, body, *, profile=None):
        calls.append(body)
        started.set()
        await release.wait()
        return ExtractionResponse(content="ok", page_count=1)

    monkeypatch.setattr(ExtractionWorker, "extract", convert)

    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
                jobs = [asyncio.create_task(client.post("/extract", content=b"%PDF-same", headers={"Content-Type": "application/pdf"})) for _ in range(10)]
                await asyncio.wait_for(started.wait(), 2)
                await asyncio.sleep(.05)
                release.set()
                results = await asyncio.gather(*jobs)
                assert all(r.status_code == 200 for r in results)
                return (await client.get("/metrics")).text

    output = asyncio.run(exercise())
    assert len(calls) == 1
    assert "pdf_extractions_total 1.0" in output
    assert "pdf_singleflight_shared_total 9.0" in output
