"""Small guarded benchmark, through Traefik; never clears Redis or changes Compose.

Requires an explicitly selected, empty nonzero Redis DB in both replicas.
Run from the repository root on Windows, after the documented isolated setup.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

import httpx2
import pymupdf


COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.traefik.yaml"]


def command(*args):
    return subprocess.check_output(args, text=True, encoding="utf-8").strip()


def stats(values):
    values = sorted(values)
    def q(fraction):
        index = (len(values) - 1) * fraction
        low = int(index)
        return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (index - low)
    return {"min": values[0], "p50": q(.5), "p90": q(.9), "p95": q(.95), "max": values[-1]}


async def run(args, output):
    if os.name != "nt":
        raise SystemExit("This host guard requires Windows. Do not bypass it; add an equivalent Linux RAM/paging guard before benchmarking there.")
    guard = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/check-host.ps1", "-OutputPath", str(output / "host.json")])
    if guard.returncode:
        raise SystemExit("entorno no suficientemente estable para comparar")
    ids = command(*COMPOSE, "ps", "-q", "extractor").splitlines()
    if len(ids) != 2:
        raise SystemExit("Expected exactly two extractor replicas")
    inspect = json.loads(command("docker", "inspect", *ids))
    for item in inspect:
        env = dict(entry.split("=", 1) for entry in item["Config"]["Env"] if "=" in entry)
        if item["State"]["Health"]["Status"] != "healthy" or env.get("REDIS_URL") != f"redis://redis:6379/{args.redis_db}" or env.get("CACHE_ENABLED", "true").lower() != "true":
            raise SystemExit("Replicas must be healthy and use the selected isolated cache DB")
    if command(*COMPOSE, "exec", "-T", "redis", "redis-cli", "-n", str(args.redis_db), "DBSIZE") != "0":
        raise SystemExit("Benchmark DB is not empty. Choose another unused DB; nothing was deleted.")
    port = command(*COMPOSE, "port", "traefik", "80").rsplit(":", 1)[1]
    url = f"http://localhost:{port}/extract"
    body = args.pdf.read_bytes()
    if args.pdf.name.lower() == "pdf279hojas.pdf":
        raise SystemExit("Use a small/official PDF for this specific benchmark")
    with pymupdf.open(stream=body, filetype="pdf") as doc:
        pages = doc.page_count
    sha = hashlib.sha256(body).hexdigest()
    key = "extract:v4:" + sha
    prefix = "singleflight-" + uuid.uuid4().hex
    since = datetime.now(timezone.utc).isoformat()
    resources = []
    stop = threading.Event()

    def monitor():
        while not stop.is_set():
            resources.append({"at": datetime.now(timezone.utc).isoformat(), "stats": command("docker", "stats", "--no-stream", "--format", "{{json .}}", *ids)})
            stop.wait(.2)

    sampler = threading.Thread(target=monitor)
    sampler.start()
    try:
        async with httpx2.AsyncClient(timeout=30) as client:
            async def post(number):
                start = time.perf_counter()
                try:
                    response = await client.post(url, content=body, headers={"Content-Type": "application/pdf", "X-Audit-Id": f"{prefix}-{number}"})
                    payload = response.json() if response.status_code == 200 else {}
                    return {"ms": (time.perf_counter() - start) * 1000, "status": response.status_code, "cache": response.headers.get("X-Cache"), "pages": payload.get("page_count"), "text_sha256": hashlib.sha256(payload.get("content", "").encode()).hexdigest() if payload else None}
                except httpx2.RequestError as exc:
                    return {"ms": (time.perf_counter() - start) * 1000, "status": 0, "error": type(exc).__name__}
            results = await asyncio.gather(*(post(i) for i in range(10)))
    finally:
        stop.set()
        sampler.join()
    conversions, distribution = {}, {}
    for item in inspect:
        name = item["Name"].lstrip("/")
        log = command("docker", "logs", "--since", since, item["Id"])
        (output / f"{name}.log").write_text(log, encoding="utf-8")
        conversions[name] = sum("EXTRACTION " in line and key in line for line in log.splitlines())
        distribution[name] = sum("PROFILE " in line and prefix in line for line in log.splitlines())
    success = [result for result in results if result["status"] == 200]
    report = {
        "url": url, "pdf": str(args.pdf.resolve()), "bytes": len(body), "pdf_sha256": sha,
        "page_count": pages, "cache_initial": "empty isolated DB", "redis_db": args.redis_db,
        "requests": 10, "http_200": len(success), "status": dict(Counter(r["status"] for r in results)),
        "latency_ms": stats([r["ms"] for r in results]), "results": results,
        "extractions_per_replica": conversions, "extractions_total": sum(conversions.values()),
        "distribution": distribution, "resources": resources,
        "content_consistent": len(success) == 10 and all(r["pages"] == pages for r in success) and len({r["text_sha256"] for r in success}) == 1,
        "scope": "Singleflight is per replica. Two replicas may perform two conversions; this is not a global single conversion guarantee.",
    }
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("resources", "results")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--redis-db", type=int, choices=range(1, 16), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(run(args, args.output))
