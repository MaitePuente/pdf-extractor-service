import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    cache_timeout_seconds: float = Field(default=0.2, gt=0, allow_inf_nan=False)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            **{
                field: os.environ[field.upper()]
                for field in cls.model_fields
                if field.upper() in os.environ
            }
        )
