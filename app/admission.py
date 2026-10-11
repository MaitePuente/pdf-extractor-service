"""Bounded FIFO gates. Mutations are atomic within the owning event loop."""
import asyncio
from collections import deque
from math import ceil

from fastapi import HTTPException


class Lease:
    def __init__(self, gate):
        self.gate = gate

    def release(self):
        if self.gate is not None:
            gate, self.gate = self.gate, None
            gate.release()


class AdmissionGate:
    def __init__(self, capacity, queue_size, timeout, metrics=None):
        self.capacity = capacity
        self.queue_size = queue_size
        self.timeout = timeout
        self.active = 0
        self.waiters = deque()
        self.metrics = metrics

    def rejected(self, reason):
        if self.metrics is not None:
            self.metrics.rejected.labels(reason).inc()
        return HTTPException(429, "Admission capacity exhausted; retry later", headers={"Retry-After": str(max(1, ceil(self.timeout)))})

    async def acquire(self):
        if self.active < self.capacity:
            self.active += 1
            return Lease(self)
        if len(self.waiters) >= self.queue_size:
            raise self.rejected("queue_full")
        future = asyncio.get_running_loop().create_future()
        self.waiters.append(future)
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.timeout)
        except BaseException as exc:
            # Handle cancellation racing with the grant, without losing a slot.
            if future.done() and not future.cancelled():
                future.result().release()
            else:
                self.waiters.remove(future)
                future.cancel()
            if isinstance(exc, TimeoutError):
                raise self.rejected("timeout") from exc
            raise

    def release(self):
        if self.waiters:
            self.waiters.popleft().set_result(Lease(self))
        else:
            self.active -= 1


async def read_pdf(request, limit):
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > limit:
            raise HTTPException(413, "PDF exceeds MAX_UPLOAD_MB")
        chunks.extend(chunk)
    return bytes(chunks)
