"""Server-side phase durations. JSON logs only; the public contract is unchanged."""
import json
import logging
import sys
from time import perf_counter

from fastapi.routing import APIRoute

logger = logging.getLogger("extractor.profile")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
logger.setLevel(logging.INFO)


class ProfiledRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            start = perf_counter()
            response = await original(request)
            profile = getattr(request.state, "profile", None)
            if profile is not None:
                now = perf_counter()
                ready = profile.pop("ready_at")
                profile.update(
                    audit_id=request.headers.get("X-Audit-Id", ""),
                    status=response.status_code,
                    # FastAPI's actual validation, serialization and Response
                    # construction, after the endpoint returns (not socket I/O).
                    serialization_ms=(now - ready) * 1000,
                    route_ms=(now - start) * 1000,
                )
                profile.update(
                    receive_body_ms=profile.get("read_body_ms", 0),
                    sha256_ms=profile.get("checksum_ms", 0),
                    redis_get_ms=profile.get("redis_get_ms", 0),
                    extraction_ms=profile.get("algorithm_ms", 0),
                    response_build_ms=profile["serialization_ms"],
                    total_server_ms=profile["route_ms"],
                )
                logger.info("PROFILE %s", json.dumps(profile, sort_keys=True))
            return response

        return handler
