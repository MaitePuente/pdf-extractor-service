"""One isolated CPU worker per API; no queue of pending PDF conversions."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
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
    def __init__(self):
        # PyMuPDF explicitly does not support concurrent use from threads.
        self.pool = ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        )
        self.busy = False

    async def extract(self, body: bytes, *, profile=None) -> ExtractionResponse:
        if self.busy:
            raise HTTPException(status_code=503, detail="Extractor is busy; try again later")
        self.busy = True
        try:
            future = asyncio.get_running_loop().run_in_executor(
                self.pool, convert_in_process, body
            )
        except BaseException:
            self.busy = False
            raise

        def finished(_):
            self.busy = False

        # A disconnected client must not admit a second job while its first
        # conversion still runs. Cancellation does not cancel CPU work.
        future.add_done_callback(finished)
        value, status, detail, timings = await asyncio.shield(future)
        if profile is not None:
            profile.update(timings)
        if status is not None:
            raise HTTPException(status_code=status, detail=detail)
        return ExtractionResponse.model_validate(value)

    async def close(self):
        await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)
