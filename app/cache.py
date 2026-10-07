import asyncio
import hashlib
import logging
import sys
from time import perf_counter

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from app.config import Settings
from app.extractor import ExtractionResponse

logger = logging.getLogger("extractor.cache")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class ExtractionCache:
    def __init__(self, settings: Settings):
        self.ttl_seconds = settings.cache_ttl_seconds
        self.timeout_seconds = settings.cache_timeout_seconds
        self.enabled = settings.cache_enabled
        self.client = None
        if self.enabled:
            try:
                # One persistent pool per API process. Warm-up remains fail open.
                self.client = Redis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=self.timeout_seconds,
                    socket_timeout=self.timeout_seconds,
                    retry=Retry(NoBackoff(), 0),
                )
            except (RedisError, ValueError) as exc:
                logger.warning("CACHE ERROR operation=init reason=%s", type(exc).__name__)

    async def warmup(self) -> None:
        if self.client is None:
            return
        started = perf_counter()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.client.ping()
        except (RedisError, TimeoutError) as exc:
            logger.warning("CACHE ERROR operation=warmup reason=%s elapsed_ms=%.3f",
                           type(exc).__name__, (perf_counter() - started) * 1000)
        else:
            logger.info("CACHE WARMUP READY elapsed_ms=%.3f", (perf_counter() - started) * 1000)

    async def close(self) -> None:
        if self.client is not None:
            try:
                await self.client.aclose()
            except RedisError as exc:
                logger.warning("CACHE ERROR operation=close reason=%s", type(exc).__name__)

    @staticmethod
    def key(body: bytes) -> str:
        # Version the blocks engine; retain old Layout/spans/text cache entries.
        return "extract:v4:" + hashlib.sha256(body).hexdigest()

    async def get(self, key: str, *, profile=None) -> tuple[ExtractionResponse | None, str]:
        if self.client is None:
            if self.enabled:
                logger.warning("CACHE ERROR operation=get reason=ClientUnavailable")
                return None, "ERROR"
            logger.info("CACHE BYPASS")
            return None, "BYPASS"
        started = perf_counter()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                value = await self.client.get(key)
        except (RedisError, TimeoutError) as exc:
            logger.warning("CACHE ERROR operation=get reason=%s", type(exc).__name__)
            return None, "ERROR"
        finally:
            if profile is not None:
                profile["redis_get_ms"] = (perf_counter() - started) * 1000
        if value is None:
            logger.info("CACHE MISS")
            return None, "MISS"
        started = perf_counter()
        try:
            result = ExtractionResponse.model_validate_json(value, strict=True)
        except ValidationError as exc:
            logger.warning("CACHE ERROR operation=decode reason=%s", type(exc).__name__)
            return None, "ERROR"
        finally:
            if profile is not None:
                profile["cache_decode_ms"] = (perf_counter() - started) * 1000
        logger.info("CACHE HIT")
        return result, "HIT"

    async def set(self, key: str, result: ExtractionResponse) -> str:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.client.set(key, result.model_dump_json(), ex=self.ttl_seconds)
        except (RedisError, TimeoutError) as exc:
            logger.warning("CACHE ERROR operation=set reason=%s", type(exc).__name__)
            return "ERROR"
        return "MISS"
