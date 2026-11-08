"""Fatal worker state and its boundary with ordinary request failures."""
import asyncio
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import httpx2
import pymupdf
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.worker import ExtractionWorker
import app.server as server_module


def small_pdf() -> bytes:
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Worker recovery test")
        return document.tobytes()


@pytest.mark.parametrize("failure_at_submit", [True, False])
def test_broken_pool_is_fatal_once_and_rejects_subsequent_jobs(failure_at_submit):
    class BrokenPool:
        _processes = {}

        def submit(self, *_args):
            if failure_at_submit:
                raise BrokenProcessPool("child died")
            future = Future()
            future.set_exception(BrokenProcessPool("child died"))
            return future

        def shutdown(self, **_kwargs):
            pass

    async def exercise():
        notifications = []
        worker = ExtractionWorker(on_broken=lambda: notifications.append("broken"))
        worker.pool = BrokenPool()
        for _ in range(2):
            with pytest.raises(HTTPException) as raised:
                await worker.extract(b"%PDF")
            assert raised.value.status_code == 503
        await asyncio.sleep(0)
        assert worker.broken is True
        assert notifications == ["broken"]
        assert worker.active == 0
        await worker.close()

    asyncio.run(exercise())


def test_broken_readiness_is_persistent_but_liveness_survives():
    application = create_app()
    with TestClient(application) as client:
        application.state.worker.mark_broken()
        for _ in range(2):
            ready = client.get("/health/ready")
            assert ready.status_code == 503
            assert ready.json() == {
                "status": "unavailable",
                "dependencies": {"worker": "broken", "redis": "unknown"},
            }
            rejected = client.post(
                "/extract", content=small_pdf(), headers={"Content-Type": "application/pdf"}
            )
            assert rejected.status_code == 503
        assert client.get("/health/live").status_code == 200
        assert application.state.service.requests.active == 0
        assert application.state.worker.active == 0


def test_cancelled_request_still_detects_later_pool_failure():
    class PendingPool:
        _processes = {}

        def __init__(self):
            self.future = Future()

        def submit(self, *_args):
            return self.future

        def shutdown(self, **_kwargs):
            pass

    async def exercise():
        notifications = []
        pool = PendingPool()
        worker = ExtractionWorker(on_broken=lambda: notifications.append("broken"))
        worker.pool = pool
        task = asyncio.create_task(worker.extract(b"%PDF"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not worker.broken
        pool.future.set_exception(BrokenProcessPool("child died after disconnect"))
        for _ in range(3):
            await asyncio.sleep(0)
        assert worker.broken is True
        assert notifications == ["broken"]
        assert worker.active == 0
        await worker.close()

    asyncio.run(exercise())


def test_invalid_pdf_does_not_break_worker_or_readiness():
    application = create_app()
    with TestClient(application) as client:
        response = client.post(
            "/extract", content=b"%PDF invalid", headers={"Content-Type": "application/pdf"}
        )
        assert response.status_code == 400
        assert application.state.worker_broken is False
        assert client.get("/health/ready").status_code == 200


def test_startup_probe_creates_child_once_before_readiness():
    application = create_app()
    with TestClient(application) as client:
        children = set(application.state.worker.pool._processes)
        assert len(children) == 1
        assert client.get("/health/ready").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert set(application.state.worker.pool._processes) == children
        assert application.state.worker_broken is False


def test_active_and_pending_requests_release_admission_after_pool_breaks():
    application = create_app()
    body = small_pdf()

    async def exercise():
        async with application.router.lifespan_context(application):
            started = asyncio.Event()
            fail = asyncio.Event()
            worker = application.state.worker

            async def failing_extract(_body, *, profile=None):
                if worker.broken:
                    raise HTTPException(503, "Extraction worker unavailable")
                started.set()
                await fail.wait()
                worker.mark_broken()
                raise HTTPException(503, "Extraction worker unavailable")

            worker.extract = failing_extract
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=application), base_url="http://test"
            ) as client:
                first = asyncio.create_task(client.post(
                    "/extract", content=body, headers={"Content-Type": "application/pdf"}
                ))
                await asyncio.wait_for(started.wait(), timeout=2)
                second = asyncio.create_task(client.post(
                    "/extract", content=body + b"\n", headers={"Content-Type": "application/pdf"}
                ))
                async def wait_for_queue():
                    while not application.state.service.cpu.waiters:
                        await asyncio.sleep(0.001)

                await asyncio.wait_for(wait_for_queue(), timeout=2)
                fail.set()
                assert (await first).status_code == 503
                assert (await second).status_code == 503
                assert (await client.get("/health/ready")).status_code == 503
            await asyncio.sleep(0)
            service = application.state.service
            assert service.requests.active == 0
            assert service.bodies.active == 0
            assert service.cpu.active == 0
            assert not service.cpu.waiters
            assert worker.active == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("broken, expected", [(False, 0), (True, 70)])
def test_server_exit_code_depends_only_on_fatal_worker(monkeypatch, broken, expected):
    class FakeServer:
        def __init__(self, _config):
            self.should_exit = False

        def run(self):
            server_module.app.state.worker_broken = broken

    monkeypatch.setattr(server_module, "ExtractorServer", FakeServer)
    assert server_module.run_server() == expected
    assert isinstance(server_module.app.state.server, FakeServer)
    server_module.app.state.server = None
    server_module.app.state.worker_broken = False
