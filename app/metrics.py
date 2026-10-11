"""Per-process Prometheus metrics with fixed, low-cardinality labels."""
from time import perf_counter

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response


class Metrics:
    def __init__(self):
        registry = self.registry = CollectorRegistry()
        self.http_requests = Counter("pdf_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry)
        self.http_duration = Histogram("pdf_http_request_duration_seconds", "HTTP response time", registry=registry,
                                       buckets=(.005, .01, .025, .05, .1, .2, .4, 1, 2, 5, 10, 30, float("inf")))
        self.extraction_duration = Histogram("pdf_extraction_duration_seconds", "PDF conversion time", registry=registry,
                                             buckets=(.025, .05, .1, .2, .4, .8, 1, 2, 5, 10, 30, float("inf")))
        self.body_duration = Histogram("pdf_request_body_receive_seconds", "PDF body receive time", registry=registry,
                                       buckets=(.005, .01, .025, .05, .1, .2, .4, 1, 2, 5, float("inf")))
        self.cache_requests = Counter("pdf_cache_requests_total", "Cache results", ["result"], registry=registry)
        self.inflight = Gauge("pdf_inflight_requests", "Current HTTP requests", registry=registry)
        self.extraction_inflight = Gauge("pdf_extraction_inflight", "Current PDF conversions", registry=registry)
        self.queue_size = Gauge("pdf_admission_queue_size", "Queued requests", registry=registry)
        self.rejected = Counter("pdf_rejected_requests_total", "Rejected requests", ["reason"], registry=registry)
        self.shared = Counter("pdf_singleflight_shared_total", "Requests sharing conversion", registry=registry)
        self.extractions = Counter("pdf_extractions_total", "Actual conversion attempts", registry=registry)
        self.http_requests.labels("GET", "/health", "200")
        for result in ("hit", "miss", "error", "bypass"):
            self.cache_requests.labels(result)
        for reason in ("queue_full", "timeout", "payload_too_large"):
            self.rejected.labels(reason)

    def render(self):
        return Response(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)


class MetricsMiddleware:
    def __init__(self, app, metrics: Metrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":
            return await self.app(scope, receive, send)
        started, status = perf_counter(), 500
        self.metrics.inflight.inc()

        async def instrumented_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, instrumented_send)
        finally:
            self.metrics.inflight.dec()
            # Only fixed route names are permitted; never use an arbitrary URL.
            route = scope["path"] if scope["path"] in ("/health", "/health/live", "/health/ready", "/extract", "/docs", "/openapi.json") else "/unmatched"
            self.metrics.http_requests.labels(scope["method"], route, str(status)).inc()
            self.metrics.http_duration.observe(perf_counter() - started)
