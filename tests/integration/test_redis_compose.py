"""Opt-in HTTP integration against the real Compose API and Redis, without mocks."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import uuid

import pymupdf
import pytest


pytestmark = pytest.mark.integration
SERVICE_ROOT = Path(__file__).resolve().parents[2]


def compose(*args):
    completed = subprocess.run(
        ["docker", "compose", "-f", str(SERVICE_ROOT / "compose.yaml"), *args],
        cwd=SERVICE_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def redis_command(*args):
    return compose("exec", "-T", "redis", "redis-cli", "--raw", *args)


def test_real_redis_miss_hit_and_ttl():
    base_url = os.environ.get("EXTRACTOR_BASE_URL")
    if not base_url:
        address = compose("port", "extractor", "8000")
        base_url = f"http://{address}"
    with urllib.request.urlopen(f"{base_url}/health", timeout=10) as response:
        assert response.status == 200
        assert json.load(response) == {"status": "ok", "service": "extractor"}

    token = uuid.uuid4().hex
    with pymupdf.open() as document:
        for page_number in (1, 2):
            document.new_page().insert_text(
                (72, 100), f"Redis integration {token} page {page_number}"
            )
        body = document.tobytes()
    key = "extract:v4:" + hashlib.sha256(body).hexdigest()
    configured_ttl = int(compose("exec", "-T", "extractor", "printenv", "CACHE_TTL_SECONDS"))

    # Only this test's unique key is deleted; never FLUSHDB/FLUSHALL.
    redis_command("DEL", key)
    try:
        assert redis_command("EXISTS", key) == "0"
        request = urllib.request.Request(
            f"{base_url}/extract", data=body, headers={"Content-Type": "application/pdf"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200
            first_status = response.headers["X-Cache"]
            first = json.load(response)
        assert first_status == "MISS"
        ttl_before = int(redis_command("PTTL", key))
        assert 0 < ttl_before <= configured_ttl * 1000
        assert json.loads(redis_command("GET", key)) == first

        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200
            second_status = response.headers["X-Cache"]
            second = json.load(response)
        assert second_status == "HIT"
        assert set(first) == set(second) == {"content", "page_count"}
        assert first == second
        assert first["page_count"] == 2
        assert token in first["content"]
        ttl_after = int(redis_command("PTTL", key))
        assert 0 < ttl_after <= ttl_before
        print(json.dumps({
            "first": first_status, "second": second_status,
            "result": second, "configured_ttl_seconds": configured_ttl,
            "pttl_before_ms": ttl_before, "pttl_after_ms": ttl_after,
        }, ensure_ascii=False))
    finally:
        redis_command("DEL", key)
