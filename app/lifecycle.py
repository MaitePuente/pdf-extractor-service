"""Application startup, worker recovery and bounded shutdown."""
import asyncio
import os
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI

from app.cache import ExtractionCache
from app.config import Settings
from app.service import ExtractionService
from app.worker import ExtractionWorker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    cache = ExtractionCache(settings)
    app.state.settings = settings
    app.state.shutting_down = False
    app.state.shutdown_started = None
    app.state.cache = cache
    app.state.worker_broken = False

    def on_broken():
        if app.state.worker_broken:
            return
        app.state.worker_broken = True
        app.state.shutting_down = True
        app.state.shutdown_started = monotonic()

        async def stop_after_drain():
            deadline = monotonic() + 3
            while app.state.service.requests.active and monotonic() < deadline:
                await asyncio.sleep(0.02)
            # Allow a bounded window for the readiness probe to observe 503.
            await asyncio.sleep(1.5)
            app.state.server.should_exit = True

        if app.state.server is not None:
            app.state.failure_exit_task = asyncio.create_task(stop_after_drain())

    app.state.worker = ExtractionWorker(settings.extraction_concurrency, on_broken=on_broken)
    app.state.service = ExtractionService(settings, cache, app.state.worker, app.state.metrics, app.state.tracer)
    if app.state.metrics is not None:
        app.state.metrics.extraction_inflight.set_function(lambda: app.state.worker.active)
        app.state.metrics.queue_size.set_function(lambda: len(app.state.service.bodies.waiters) + len(app.state.service.cpu.waiters))
    try:
        # Spawn the extraction child once before the replica becomes ready.
        await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(app.state.worker.pool, os.getpid),
            timeout=settings.worker_startup_timeout_seconds,
        )
        await cache.warmup()
        yield
    finally:
        app.state.shutting_down = True
        if app.state.shutdown_started is None:
            app.state.shutdown_started = monotonic()
        remaining = max(0.01, settings.graceful_shutdown_timeout_seconds - (monotonic() - app.state.shutdown_started))
        try:
            await asyncio.wait_for(app.state.service.close(), timeout=remaining)
            remaining = max(0.01, settings.graceful_shutdown_timeout_seconds - (monotonic() - app.state.shutdown_started))
            await asyncio.wait_for(app.state.worker.close(), timeout=remaining)
        except TimeoutError:
            await app.state.worker.force_close()
        finally:
            try:
                await asyncio.wait_for(cache.close(), timeout=2)
            except TimeoutError:
                pass
        if app.state.otel_provider is not None:
            try:
                await asyncio.wait_for(asyncio.to_thread(app.state.otel_provider.shutdown), timeout=2)
            except TimeoutError:
                pass
