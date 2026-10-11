import signal
import asyncio
from time import perf_counter

import uvicorn
from fastapi.testclient import TestClient

from app.main import app
from app.server import ExtractorServer
from app.main import create_app
from app.service import ExtractionService
from app.worker import ExtractionWorker


def test_stop_signal_rejects_new_extraction_and_fails_readiness():
    with TestClient(app) as client:
        server = ExtractorServer(uvicorn.Config(app))
        server.handle_exit(signal.SIGTERM, None)
        assert app.state.shutting_down is True
        assert app.state.shutdown_started is not None
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        rejected = client.post("/extract", content=b"%PDF", headers={"Content-Type": "application/pdf"})
        assert rejected.status_code == 503
        assert rejected.headers["content-type"] == "application/problem+json"


def test_shutdown_does_not_wait_forever_for_stalled_flight(monkeypatch):
    monkeypatch.setenv("GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
    application = create_app()
    forced = []

    async def stalled(self):
        await asyncio.sleep(10)

    original_force = ExtractionWorker.force_close

    async def force(self):
        forced.append(True)
        await original_force(self)

    monkeypatch.setattr(ExtractionService, "close", stalled)
    monkeypatch.setattr(ExtractionWorker, "force_close", force)
    start = perf_counter()
    with TestClient(application):
        pass
    assert perf_counter() - start < 2
    assert forced == [True]
