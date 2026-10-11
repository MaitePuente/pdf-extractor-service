import asyncio

import pytest
from fastapi import HTTPException

from app.admission import AdmissionGate
from app.config import Settings
from app.worker import ExtractionWorker


def test_cancelled_queue_waiter_does_not_leak_or_steal_capacity():
    async def exercise():
        gate = AdmissionGate(1, 1, 1)
        first = await gate.acquire()
        waiting = asyncio.create_task(gate.acquire())
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        first.release()
        next_lease = await gate.acquire()
        next_lease.release()
        assert gate.active == 0
        assert not gate.waiters

    asyncio.run(exercise())


def test_cancellation_racing_with_grant_returns_slot():
    async def exercise():
        gate = AdmissionGate(1, 1, 1)
        first = await gate.acquire()
        waiting = asyncio.create_task(gate.acquire())
        await asyncio.sleep(0)
        first.release()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert gate.active == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("options", [{"max_in_flight": 0}, {"queue_size": -1}, {"extraction_concurrency": 5}, {"admission_timeout_seconds": float("inf")}, {"max_upload_mb": 0}])
def test_invalid_capacity_configuration_fails_startup(options):
    with pytest.raises(ValueError):
        Settings(**options)


def test_unavailable_worker_returns_503_not_overload_429():
    async def exercise():
        worker = ExtractionWorker()
        await worker.close()
        with pytest.raises(HTTPException) as raised:
            await worker.extract(b"%PDF")
        assert raised.value.status_code == 503
        assert worker.active == 0

    asyncio.run(exercise())
