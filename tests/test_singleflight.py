import asyncio

import httpx2
import pytest

from app.extractor import ExtractionResponse
from app.main import app
from app.worker import ExtractionWorker
from fastapi import HTTPException


@pytest.mark.parametrize("distinct", [False, True])
def test_ten_concurrent_requests_coalesce_only_identical_bytes(monkeypatch, distinct):
    async def exercise():
        calls = []
        started = asyncio.Event()
        release = asyncio.Event()

        async def convert(self, body, *, profile=None):
            calls.append(body)
            started.set()
            await release.wait()
            return ExtractionResponse(content=body.decode(), page_count=1)

        monkeypatch.setattr(ExtractionWorker, "extract", convert)
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
                jobs = [asyncio.create_task(client.post("/extract", content=f"%PDF-{i if distinct else 0}".encode(), headers={"Content-Type": "application/pdf"})) for i in range(10)]
                try:
                    await asyncio.wait_for(started.wait(), 2)
                    # Let all clients join the same pending conversion.
                    await asyncio.sleep(0.05)
                    if not distinct:
                        assert len(calls) == 1
                finally:
                    release.set()
                    responses = await asyncio.gather(*jobs)
                assert all(r.status_code == 200 for r in responses)
                assert len(calls) == (10 if distinct else 1)
                assert len({r.json()["content"] for r in responses}) == (10 if distinct else 1)

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [False, True])
def test_cancelled_leader_does_not_cancel_follower_and_cleanup_allows_retry(monkeypatch, failure):
    async def exercise():
        calls = 0
        started, release = asyncio.Event(), asyncio.Event()

        async def convert(self, body, *, profile=None):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            if failure and calls == 1:
                raise HTTPException(503, "Worker failed")
            return ExtractionResponse(content="ok", page_count=1)

        monkeypatch.setattr(ExtractionWorker, "extract", convert)
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
                async def post():
                    return await client.post("/extract", content=b"%PDF-same", headers={"Content-Type": "application/pdf"})
                leader = asyncio.create_task(post())
                await started.wait()
                follower = asyncio.create_task(post())
                await asyncio.sleep(0.02)
                leader.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await leader
                release.set()
                assert (await follower).status_code == (503 if failure else 200)
                assert calls == 1
                assert (await post()).status_code == 200
                assert calls == 2  # BYPASS: completed flights are not a hidden cache.
                assert app.state.service.bodies.active == 0

    asyncio.run(exercise())


def test_distinct_pdfs_can_use_configured_two_cpu_slots(monkeypatch):
    monkeypatch.setenv("EXTRACTION_CONCURRENCY", "2")

    async def exercise():
        calls = 0
        both, release = asyncio.Event(), asyncio.Event()

        async def convert(self, body, *, profile=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                both.set()
            await release.wait()
            return ExtractionResponse(content=body.decode(), page_count=1)

        monkeypatch.setattr(ExtractionWorker, "extract", convert)
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
                jobs = [asyncio.create_task(client.post("/extract", content=f"%PDF-{n}".encode(), headers={"Content-Type": "application/pdf"})) for n in range(2)]
                try:
                    await asyncio.wait_for(both.wait(), 1)
                finally:
                    release.set()
                    results = await asyncio.gather(*jobs)
                assert all(r.status_code == 200 for r in results)

    asyncio.run(exercise())
