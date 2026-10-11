"""Configurable isolated CPU processes; admission is handled by the service."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import multiprocessing

from fastapi import HTTPException

from app.extractor import ExtractionResponse, extract_pdf


def convert_in_process(body: bytes) -> tuple[dict | None, int | None, str | None, dict]:
    # HTTPException is not reliably pickleable across a spawn boundary.
    try:
        timings = {}
        return extract_pdf(body, timings=timings).model_dump(), None, None, timings
    except HTTPException as exc:
        return None, exc.status_code, exc.detail, {}


class ExtractionWorker:
    def __init__(self, concurrency=1):
        # PyMuPDF explicitly does not support concurrent use from threads.
        self.pool = ProcessPoolExecutor(
            max_workers=concurrency, mp_context=multiprocessing.get_context("spawn")
        )
        self.concurrency = concurrency
        self.active = 0
        self._closing_processes = []

    async def extract(self, body: bytes, *, profile=None) -> ExtractionResponse:
        if self.active >= self.concurrency:
            raise HTTPException(429, "CPU capacity exhausted", headers={"Retry-After": "1"})
        self.active += 1
        try:
            future = asyncio.get_running_loop().run_in_executor(
                self.pool, convert_in_process, body
            )
        except (BrokenProcessPool, RuntimeError) as exc:
            self.active -= 1
            raise HTTPException(503, "Extraction worker unavailable") from exc
        except BaseException:
            self.active -= 1
            raise

        def finished(_):
            self.active -= 1

        # A disconnected client must not admit a second job while its first
        # conversion still runs. Cancellation does not cancel CPU work.
        future.add_done_callback(finished)
        try:
            value, status, detail, timings = await asyncio.shield(future)
        except BrokenProcessPool as exc:
            raise HTTPException(503, "Extraction worker unavailable") from exc
        if profile is not None:
            profile.update(timings)
        if status is not None:
            raise HTTPException(status_code=status, detail=detail)
        return ExtractionResponse.model_validate(value)

    async def close(self):
        self._closing_processes = list((self.pool._processes or {}).values())
        await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)

    async def force_close(self):
        """Stop only this executor's child processes after the drain deadline."""
        def terminate():
            processes = self._closing_processes or list((self.pool._processes or {}).values())
            for process in processes:
                if process.is_alive():
                    process.terminate()
            for process in processes:
                process.join(timeout=0.2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.2)
            self.pool.shutdown(wait=False, cancel_futures=True)

        await asyncio.to_thread(terminate)
