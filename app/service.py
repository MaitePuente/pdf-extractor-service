"""Coordinate cache misses; followers never own additional CPU slots."""
import json
import logging
from time import perf_counter

from app.admission import AdmissionGate
from app.singleflight import SingleFlight
from app.tracing import span

logger = logging.getLogger("extractor.profile")


class ExtractionService:
    def __init__(self, settings, cache, worker, metrics=None, tracer=None):
        self.cache, self.worker = cache, worker
        self.metrics = metrics
        self.tracer = tracer
        self.flights = SingleFlight()
        self.requests = AdmissionGate(settings.max_in_flight + settings.queue_size, 0, settings.admission_timeout_seconds, metrics)
        self.bodies = AdmissionGate(settings.max_in_flight, settings.queue_size, settings.admission_timeout_seconds, metrics)
        self.cpu = AdmissionGate(settings.extraction_concurrency, settings.queue_size, settings.admission_timeout_seconds, metrics)

    async def join(self, key, body, status, body_lease, request_id=""):
        return await self.flights.join(key, lambda: self.convert(key, body, status, body_lease, request_id))

    async def convert(self, key, body, status, body_lease, request_id=""):
        timings = {}
        try:
            # A previous flight may have populated Redis between GET and join.
            if status == "MISS":
                recheck = {}
                with span(self.tracer, "redis_get"):
                    cached, status = await self.cache.get(key, profile=recheck)
                # Keep each request's initial GET measurement intact. These
                # durations belong to the shared producer, not its followers.
                timings.update({"shared_recheck_" + name: value for name, value in recheck.items()})
                if cached is not None:
                    return cached, status, timings
            with span(self.tracer, "admission_wait"):
                lease = await self.cpu.acquire()
            try:
                logger.info("EXTRACTION %s", json.dumps({"request_id": request_id}))
                if self.metrics is not None:
                    self.metrics.extractions.inc()
                start = perf_counter()
                with span(self.tracer, "pdf_extract", request_id):
                    result = await self.worker.extract(body, profile=timings)
                timings["worker_ms"] = (perf_counter() - start) * 1000
                if self.metrics is not None and "algorithm_ms" in timings:
                    self.metrics.extraction_duration.observe(timings["algorithm_ms"] / 1000)
            finally:
                lease.release()
            if status == "MISS":
                start = perf_counter()
                with span(self.tracer, "redis_set"):
                    status = await self.cache.set(key, result)
                timings["cache_set_ms"] = (perf_counter() - start) * 1000
            return result, status, timings
        finally:
            body_lease.release()

    async def close(self):
        await self.flights.close()
