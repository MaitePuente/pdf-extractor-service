import asyncio
from contextlib import asynccontextmanager
from time import perf_counter, monotonic
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from redis.exceptions import RedisError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.cache import ExtractionCache
from app.config import Settings
from app.extractor import ExtractionResponse
from app.worker import ExtractionWorker
from app.profiling import ProfiledRoute
from app.service import ExtractionService
from app.admission import read_pdf
from app.problems import http_problem, validation_problem, internal_problem
from app.tracing import configure_tracing, span


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    cache = ExtractionCache(settings)
    app.state.settings = settings
    app.state.shutting_down = False
    app.state.shutdown_started = None
    app.state.cache = cache
    app.state.worker = ExtractionWorker(settings.extraction_concurrency)
    app.state.service = ExtractionService(settings, cache, app.state.worker, app.state.metrics, app.state.tracer)
    if app.state.metrics is not None:
        app.state.metrics.extraction_inflight.set_function(lambda: app.state.worker.active)
        app.state.metrics.queue_size.set_function(lambda: len(app.state.service.bodies.waiters) + len(app.state.service.cpu.waiters))
    try:
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


def health() -> dict[str, str]:
    return {"status": "ok", "service": "extractor"}


def live() -> dict[str, str]:
    return {"status": "ok", "service": "pdf-extractor"}


async def ready(request: Request) -> JSONResponse:
    if request.app.state.shutting_down:
        return JSONResponse({"status": "shutting_down", "dependencies": {"redis": "unknown"}}, status_code=503)
    cache = request.app.state.cache
    available = False
    if cache.client is not None:
        try:
            async with asyncio.timeout(request.app.state.settings.readiness_timeout_seconds):
                await cache.client.ping()
            available = True
        except (RedisError, TimeoutError):
            pass
    return JSONResponse(
        {"status": "ready" if available else "degraded",
         "dependencies": {"redis": "ok" if available else "unavailable"}},
        status_code=200 if available or not request.app.state.settings.readiness_redis_required else 503,
    )


async def extract(request: Request, response: Response) -> ExtractionResponse:
    if request.app.state.shutting_down:
        raise HTTPException(503, "Service is shutting down")
    metrics = request.app.state.metrics
    tracer = request.app.state.tracer
    request_id = request.state.request_id
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Content-Type must be application/pdf")
    limit = request.app.state.settings.max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdigit():
            raise HTTPException(400, "Invalid Content-Length")
        if int(declared) > limit:
            if metrics is not None:
                metrics.rejected.labels("payload_too_large").inc()
            raise HTTPException(413, "PDF exceeds MAX_UPLOAD_MB")
    service = request.app.state.service
    with span(tracer, "admission_wait", request_id):
        admission = await service.requests.acquire()
    lease = None
    try:
        with span(tracer, "admission_wait", request_id):
            lease = await service.bodies.acquire()
        start = perf_counter()
        try:
            with span(tracer, "receive_body", request_id):
                body = await read_pdf(request, limit)
        except HTTPException as exc:
            if metrics is not None and exc.status_code == 413:
                metrics.rejected.labels("payload_too_large").inc()
            raise
        profile = {"read_body_ms": (perf_counter() - start) * 1000}
        if metrics is not None:
            metrics.body_duration.observe(profile["read_body_ms"] / 1000)
        if not body:
            raise HTTPException(400, "PDF body must not be empty")
        if not body.startswith(b"%PDF"):
            raise HTTPException(400, "Body must start with %PDF")
        cache = request.app.state.cache
        start = perf_counter()
        with span(tracer, "sha256", request_id):
            key = cache.key(body)
        profile["checksum_ms"] = (perf_counter() - start) * 1000
        start = perf_counter()
        with span(tracer, "redis_get", request_id):
            result, status = await cache.get(key, profile=profile)
        if metrics is not None:
            metrics.cache_requests.labels(status.lower()).inc()
        profile["cache_get_ms"] = (perf_counter() - start) * 1000
        if result is None:
            task, leader = await service.join(key, body, status, lease, request_id)
            if not leader:
                lease.release()
                if metrics is not None:
                    metrics.shared.inc()
            # The flight now owns the leader's body lease until work completes.
            lease = None
            del body
            with span(tracer, "singleflight_wait", request_id):
                result, status, timings = await asyncio.shield(task)
            profile.update(timings, coalesced=not leader)
        response.headers["X-Cache"] = status
        profile.update(cache=status, ready_at=perf_counter())
        request.state.profile = profile
        return result
    finally:
        admission.release()
        if lease is not None:
            lease.release()


class RequestCorrelation:
    """Attach a bounded correlation ID without buffering the request body."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming_headers = [(key.lower(), value) for key, value in scope["headers"]]
        identifiers = dict(incoming_headers)
        incoming = identifiers.get(b"x-request-id") or identifiers.get(b"x-audit-id") or b""
        request_id = incoming if 0 < len(incoming) <= 128 and all(32 <= c < 127 for c in incoming) else uuid4().hex.encode()
        # ServerErrorMiddleware is outermost and sees the original scope on 500.
        # Share only the state mapping with that outer layer.
        scope["state"] = dict(scope.get("state") or {}, request_id=request_id.decode("ascii"))
        scope = dict(scope)
        scope["headers"] = [
            (key, value) for key, value in scope["headers"]
            if key.lower() not in (b"x-request-id", b"x-audit-id")
        ] + [(b"x-request-id", request_id), (b"x-audit-id", request_id)]
        if scope["app"].state.tracer is not None:
            from opentelemetry import trace
            trace.get_current_span().set_attribute("request.id", request_id.decode("ascii"))

        async def audited_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", request_id), (b"x-audit-id", request_id)
                ]
            await send(message)

        await self.app(scope, receive, audited_send)


def create_app():
    settings = Settings.from_env()
    docs = settings.docs_enabled
    application = FastAPI(
        title="PDF Extractor Service", version="1.0.0",
        description="Convert binary PDF documents to Markdown entirely in memory. Shared Redis cache and bounded per-replica extraction; no file persistence or OCR.",
        lifespan=lifespan, docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None, openapi_url="/openapi.json" if docs else None,
    )
    application.router.route_class = ProfiledRoute
    application.add_middleware(RequestCorrelation)
    application.state.metrics = None
    if settings.metrics_enabled:
        from app.metrics import Metrics, MetricsMiddleware
        application.state.metrics = Metrics()
        application.add_middleware(MetricsMiddleware, metrics=application.state.metrics)
    application.state.tracer, application.state.otel_provider = configure_tracing(application, settings)
    if application.state.tracer is not None:
        class TracingJSONResponse(JSONResponse):
            def render(self, content):
                # Only JSON encoding is timed here; model validation is separate.
                with span(application.state.tracer, "serialize_response"):
                    return super().render(content)

        application.router.default_response_class = TracingJSONResponse
    if application.state.metrics is not None:
        application.add_api_route("/metrics", lambda: application.state.metrics.render(), methods=["GET"], include_in_schema=False)
    application.add_exception_handler(StarletteHTTPException, http_problem)
    application.add_exception_handler(RequestValidationError, validation_problem)
    application.add_exception_handler(Exception, internal_problem)
    application.add_api_route("/health", health, methods=["GET"], tags=["Health"], summary="API liveness (not a Redis dependency check)")
    application.add_api_route("/health/live", live, methods=["GET"], tags=["Health"], summary="Process liveness without Redis")
    application.add_api_route("/health/ready", ready, methods=["GET"], tags=["Health"], summary="Readiness with short Redis probe", responses={503: {"description": "Shutting down or required Redis unavailable"}})
    problem_schema = {"type": "object", "required": ["type", "title", "status", "detail", "instance", "request_id"],
                      "properties": {"type": {"type": "string"}, "title": {"type": "string"}, "status": {"type": "integer"},
                                     "detail": {"type": "string"}, "instance": {"type": "string"}, "request_id": {"type": "string"}}}
    responses = {code: {"description": description, "content": {"application/problem+json": {"schema": problem_schema}}} for code, description in {
        400: "Empty, invalid or encrypted PDF", 413: "Upload exceeds MAX_UPLOAD_MB",
        415: "Content-Type must be application/pdf", 422: "Invalid request parameters", 429: "Admission queue full or timeout; retry after Retry-After seconds",
        503: "Extraction worker unavailable", 500: "Unexpected internal failure",
    }.items()}
    responses[429]["headers"] = {"Retry-After": {"schema": {"type": "integer"}}}
    responses[200] = {
        "description": "Markdown and original page count",
        "headers": {
            "X-Cache": {"schema": {"type": "string", "enum": ["HIT", "MISS", "ERROR", "BYPASS"]}},
            "X-Audit-Id": {"schema": {"type": "string"}, "description": "Echoed correlation ID (up to 128 printable ASCII characters), or generated ID"},
            "X-Request-ID": {"schema": {"type": "string"}, "description": "Client-provided or generated correlation ID"},
        },
        "content": {"application/json": {"example": {"content": "## Página 1\n...", "page_count": 279}}},
    }
    application.add_api_route(
        "/extract", extract, methods=["POST"], tags=["Extraction"], response_model=ExtractionResponse,
        summary="Convert PDF bytes to Markdown", responses=responses,
        openapi_extra={"requestBody": {"required": True, "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}, "parameters": [{"name": name, "in": "header", "required": False, "schema": {"type": "string", "maxLength": 128}} for name in ("X-Audit-Id", "X-Request-ID")]},
    )
    return application


app = create_app()
