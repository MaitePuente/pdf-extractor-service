"""Public RFC 9457 error representations; no exception internals in responses."""
import logging
from urllib.parse import quote

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


logger = logging.getLogger("extractor.errors")

PROBLEM_TYPES = {
    400: ("invalid-pdf", "PDF inválido"),
    413: ("payload-too-large", "PDF demasiado grande"),
    415: ("unsupported-media-type", "Tipo de contenido no admitido"),
    422: ("validation-error", "Solicitud inválida"),
    429: ("admission-rejected", "Demasiadas solicitudes"),
    500: ("internal-error", "Error interno"),
    503: ("service-unavailable", "Servicio no disponible"),
}


def problem(request: Request, status: int, detail: str, headers=None):
    request_id = getattr(request.state, "request_id", "")
    slug, title = PROBLEM_TYPES.get(status, ("http-error", "Error HTTP"))
    route = getattr(request.scope.get("route"), "path", None)
    if route is None:
        route = request.url.path if request.url.path in ("/extract", "/health", "/health/live", "/health/ready", "/metrics") else "/unmatched"
    logger.info("HTTP_ERROR status=%s route=%s request_id=%s", status, route, request_id)
    return JSONResponse(
        {
            "type": f"/errors/{slug}",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": f"{route}#{quote(request_id, safe='-._~')}",
            "request_id": request_id,
        },
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
    )


async def http_problem(request: Request, error: HTTPException):
    return problem(request, error.status_code, str(error.detail), error.headers)


async def validation_problem(request: Request, error: RequestValidationError):
    # FastAPI's validation errors can include input bytes. Never echo them.
    return problem(request, 422, "Invalid request parameters")


async def internal_problem(request: Request, error: Exception):
    # The exception text could contain a file path, PDF contents or secrets.
    return problem(request, 500, "Unexpected server error",
                   {"X-Request-ID": getattr(request.state, "request_id", ""),
                    "X-Audit-Id": getattr(request.state, "request_id", "")})
