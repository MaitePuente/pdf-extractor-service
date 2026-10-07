"""Protect the load report from hiding HTTP failures or bad successful bodies."""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("vegeta_report", Path(__file__).with_name("report.py"))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def test_http_errors_timeouts_and_cache_are_counted_separately():
    content = "Expected Markdown"
    pdf = dict(name="official.pdf", bytes=123, page_count=2, content_characters=len(content),
               content_sha256=hashlib.sha256(content.encode()).hexdigest())
    records = []
    for seq, (code, error, cache, value) in enumerate([
        (200, "", "MISS", content), (200, "", "HIT", content),
        (503, "503 Service Unavailable", None, None),
        (0, "context deadline exceeded (Client.Timeout exceeded)", None, None),
        (200, "", "ERROR", "wrong content"),
    ]):
        body = base64.b64encode(json.dumps(dict(content=value, page_count=2)).encode()).decode()
        records.append(dict(seq=seq, code=code, error=error, bytes_out=123 if code else 0,
                            headers={"X-Cache": [cache]} if cache else None, body=body))
    output = io.StringIO()
    result = report.audit_records(iter(records), [pdf], output)
    assert result["generated"] == result["terminal_results"] == 5
    assert result["http_completed"] == 4
    assert result["successful_200"] == 3
    assert result["failed"] == 2 and result["timeouts"] == 1
    assert result["cache_headers"] == {"MISS": 1, "HIT": 1, "ABSENT": 2, "ERROR": 1}
    assert result["content_validated"] == 2
    assert result["content_validation_errors"] == [{"seq": 4, "error": "Wrong Markdown SHA-256"}]
    assert len(output.getvalue().splitlines()) == 5
    assert all("body" not in json.loads(line) for line in output.getvalue().splitlines())


def test_nanoseconds_and_success_rate_are_not_confused_with_throughput():
    metrics = dict(duration=30_000_000_000, wait=30_000_000_000, requests=1500, rate=50,
                   throughput=10, success=0.4, latencies={"mean": 1_250_000_000, "95th": 30_000_000_000},
                   bytes_in={"total": 6000, "mean": 4}, bytes_out={"total": 9000, "mean": 6})
    result = report.normalize_metrics(metrics)
    assert result["latency_ms"] == {"mean": 1250, "95th": 30000}
    assert result["total_seconds"] == 60
    assert result["throughput"] == 10 and result["offered_rate"] == 50
    assert result["success_percent"] == 40 and result["error_percent"] == 60
    assert result["bytes_in_per_second"] == 100 and result["bytes_out_per_second"] == 150
