import os

from pydantic import BaseModel, Field, model_validator


class Settings(BaseModel):
    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    cache_timeout_seconds: float = Field(default=0.2, gt=0, allow_inf_nan=False)
    queue_size: int = Field(default=16, ge=0)
    max_in_flight: int = Field(default=4, gt=0)
    extraction_concurrency: int = Field(default=1, gt=0)
    admission_timeout_seconds: float = Field(default=2, gt=0, allow_inf_nan=False)
    max_upload_mb: int = Field(default=20, gt=0)
    docs_enabled: bool = True
    readiness_redis_required: bool = False
    readiness_timeout_seconds: float = Field(default=0.1, gt=0, allow_inf_nan=False)
    metrics_enabled: bool = False
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_sample_ratio: float = Field(default=0.05, ge=0, le=1, allow_inf_nan=False)
    graceful_shutdown_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_capacity(self):
        if self.extraction_concurrency > self.max_in_flight:
            raise ValueError("EXTRACTION_CONCURRENCY must not exceed MAX_IN_FLIGHT")
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint:
            raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT is required when OTEL_ENABLED=true")
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            **{
                field: os.environ[field.upper()]
                for field in cls.model_fields
                if field.upper() in os.environ
            }
        )
