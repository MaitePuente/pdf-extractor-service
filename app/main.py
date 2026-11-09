"""Create and connect the FastAPI application."""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.lifecycle import lifespan
from app.middleware import RequestCorrelation
from app.problems import http_problem, validation_problem, internal_problem
from app.profiling import ProfiledRoute
from app.routes import extract, health, live, ready, register_routes
from app.tracing import configure_tracing, span

__all__ = ["app", "create_app", "lifespan", "health", "live", "ready", "extract", "RequestCorrelation"]


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
    application.state.server = None
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
    register_routes(application)
    return application


app = create_app()
