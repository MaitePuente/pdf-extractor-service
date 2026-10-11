import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


def test_tracing_requires_exporter_endpoint():
    with pytest.raises(ValidationError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        Settings(otel_enabled=True)


def test_tracing_is_off_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    app = create_app()
    assert app.state.tracer is None
    assert app.state.otel_provider is None


def test_tracing_can_be_enabled_without_exporting_pdf_data(monkeypatch):
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    class NoNetworkExporter:
        def __init__(self, **kwargs):
            pass

        def export(self, spans):
            from opentelemetry.sdk.trace.export import SpanExportResult
            return SpanExportResult.SUCCESS

        def shutdown(self):
            pass

        def force_flush(self, timeout_millis=30000):
            return True

    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", NoNetworkExporter)
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: cls(
        otel_enabled=True, otel_exporter_otlp_endpoint="http://127.0.0.1:1/v1/traces", otel_sample_ratio=0,
    )))
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
    assert app.state.tracer is not None
    assert app.state.otel_provider is not None
