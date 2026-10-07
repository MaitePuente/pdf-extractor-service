from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request, Response

from app.cache import ExtractionCache
from app.config import Settings
from app.extractor import ExtractionResponse
from app.worker import ExtractionWorker
from app.profiling import ProfiledRoute


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = ExtractionCache(Settings.from_env())
    app.state.cache = cache
    app.state.worker = ExtractionWorker()
    try:
        await cache.warmup()
        yield
    finally:
        await app.state.worker.close()
        await cache.close()


app = FastAPI(title="PDF Extractor", version="0.1.0", lifespan=lifespan)
app.router.route_class = ProfiledRoute


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "extractor"}


@app.post("/extract", response_model=ExtractionResponse)
async def extract(request: Request, response: Response) -> ExtractionResponse:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Content-Type must be application/pdf")
    start = perf_counter()
    body = await request.body()
    profile = {"read_body_ms": (perf_counter() - start) * 1000}
    if not body:
        raise HTTPException(status_code=400, detail="PDF body must not be empty")
    if not body.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Body must start with %PDF")
    cache = request.app.state.cache
    start = perf_counter()
    key = cache.key(body)
    profile["checksum_ms"] = (perf_counter() - start) * 1000
    start = perf_counter()
    result, status = await cache.get(key, profile=profile)
    profile["cache_get_ms"] = (perf_counter() - start) * 1000
    if result is not None:
        response.headers["X-Cache"] = status
        profile.update(cache=status, ready_at=perf_counter())
        request.state.profile = profile
        return result
    start = perf_counter()
    result = await request.app.state.worker.extract(body, profile=profile)
    profile["worker_ms"] = (perf_counter() - start) * 1000
    if status == "MISS":
        start = perf_counter()
        status = await cache.set(key, result)
        profile["cache_set_ms"] = (perf_counter() - start) * 1000
    response.headers["X-Cache"] = status
    profile.update(cache=status, ready_at=perf_counter())
    request.state.profile = profile
    return result
