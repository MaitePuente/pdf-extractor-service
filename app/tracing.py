"""Optional per-app OpenTelemetry setup. No exporter threads when disabled."""
from contextlib import contextmanager


def configure_tracing(application, settings):
    if not settings.otel_enabled:
        return None, None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    provider = TracerProvider(
        resource=Resource.create({"service.name": "pdf-extractor"}),
        sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_ratio)),
    )
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint += "/v1/traces"
    exporter = OTLPSpanExporter(endpoint=endpoint, timeout=2)
    provider.add_span_processor(BatchSpanProcessor(exporter, max_export_batch_size=128, schedule_delay_millis=5000))
    FastAPIInstrumentor.instrument_app(application, tracer_provider=provider)
    return provider.get_tracer("pdf-extractor"), provider


@contextmanager
def span(tracer, name, request_id=""):
    if tracer is None:
        yield
    else:
        with tracer.start_as_current_span(name) as current:
            if request_id:
                current.set_attribute("request.id", request_id)
            yield
