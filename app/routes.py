"""HTTP endpoints and their OpenAPI registration."""
import asyncio
from time import perf_counter

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.admission import read_pdf
from app.extractor import ExtractionResponse
from app.tracing import span


def health() -> dict[str, str]:
    return {"status": "ok", "service": "extractor"}


def live() -> dict[str, str]:
    return {"status": "ok", "service": "pdf-extractor"}


async def ready(request: Request) -> JSONResponse:
    if request.app.state.worker_broken:
        return JSONResponse(
            {"status": "unavailable", "dependencies": {"worker": "broken", "redis": "unknown"}},
            status_code=503,
        )
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
    if request.app.state.worker_broken:
        raise HTTPException(503, "Extraction worker unavailable")
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



def register_routes(application):
    application.add_api_route("/health", health, methods=["GET"], tags=["Health"], summary="API liveness (not a Redis dependency check)")
    application.add_api_route("/health/live", live, methods=["GET"], tags=["Health"], summary="Process liveness without Redis")
    application.add_api_route("/health/ready", ready, methods=["GET"], tags=["Health"], summary="Readiness with short Redis probe", responses={503: {"description": "Worker broken, shutting down or required Redis unavailable"}})
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
