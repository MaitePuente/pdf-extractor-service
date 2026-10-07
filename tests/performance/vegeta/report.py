"""Audit Vegeta records without treating HTTP success or cache HIT as extraction."""
import base64
from collections import Counter
import hashlib
import json


def audit_records(records, pdfs, output):
    by_size = {pdf["bytes"]: pdf for pdf in pdfs}
    codes, caches, errors, documents = Counter(), Counter(), Counter(), Counter()
    validation_errors = []
    total = completed = successful = timeouts = validated = 0
    sequences = set()
    for record in records:
        total += 1
        sequences.add(record["seq"])
        code = int(record["code"])
        completed += code != 0
        successful += code == 200 and not record["error"]
        codes[str(code)] += 1
        error = record["error"]
        if error:
            errors[error] += 1
            timeouts += any(word in error.lower() for word in ("timeout", "deadline exceeded"))
        headers = {key.lower(): value for key, value in (record.get("headers") or {}).items()}
        cache = (headers.get("x-cache") or ["ABSENT"])[0]
        caches[cache] += 1
        pdf = by_size.get(record["bytes_out"])
        documents[pdf["name"] if pdf else "UNKNOWN"] += 1
        row = {key: value for key, value in record.items() if key != "body"}
        row.update(cache=cache, pdf=pdf["name"] if pdf else None)
        if code == 200 and not error:
            try:
                body = json.loads(base64.b64decode(record["body"], validate=True))
                assert pdf is not None, "Unrecognized request body size"
                assert set(body) == {"content", "page_count"}, "Unexpected JSON contract"
                assert body["page_count"] == pdf["page_count"], "Wrong page count"
                content = body["content"]
                assert isinstance(content, str), "Content is not a string"
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                assert digest == pdf["content_sha256"], "Wrong Markdown SHA-256"
                assert len(content) == pdf["content_characters"], "Wrong content length"
                row.update(content_sha256=digest, content_characters=len(content),
                           page_count=body["page_count"], content_valid=True)
                validated += 1
            except (AssertionError, ValueError, KeyError, TypeError) as exc:
                row.update(content_valid=False, validation_error=str(exc))
                validation_errors.append({"seq": record["seq"], "error": str(exc)})
        output.write(json.dumps(row, ensure_ascii=False) + "\n")
    started_at_least = max(sequences, default=-1) + 1
    return dict(generated=total, terminal_results=total, requests_started_at_least=started_at_least,
                unrecorded_sequences=sorted(set(range(started_at_least))-sequences), http_completed=completed,
                successful_200=successful, failed=total-successful, timeouts=timeouts,
                status_codes=dict(codes), cache_headers=dict(caches), errors=dict(errors),
                requests_by_pdf=dict(documents), content_validated=validated,
                content_validation_errors=validation_errors)


def normalize_metrics(metrics):
    seconds = (metrics["duration"] + metrics["wait"]) / 1e9
    return dict(requests=metrics["requests"], offered_rate=metrics["rate"],
                throughput=metrics["throughput"], success_percent=metrics["success"]*100,
                error_percent=(1-metrics["success"])*100,
                latency_ms={key: value/1e6 for key, value in metrics["latencies"].items()},
                attack_seconds=metrics["duration"]/1e9, wait_seconds=metrics["wait"]/1e9,
                total_seconds=seconds, bytes_in=metrics["bytes_in"], bytes_out=metrics["bytes_out"],
                bytes_in_per_second=metrics["bytes_in"]["total"]/seconds,
                bytes_out_per_second=metrics["bytes_out"]["total"]/seconds)


def main():
    """Rebuild derived reports after a reporting failure; never send HTTP requests."""
    import argparse
    import gzip
    from pathlib import Path
    import shutil
    import subprocess
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--vegeta", type=Path, default=Path("D:/herramientas/vegeta/vegeta.exe"))
    args = parser.parse_args()
    folder = args.evidence.resolve()
    root = Path(__file__).resolve().parents[3]
    if not folder.is_relative_to(root):
        parser.error("Evidence must belong to this repository")
    raw = folder / "results.bin"
    if not raw.is_file():
        parser.error("This recovery command requires the original results.bin")
    pdfs = json.loads((folder / "pdfs.json").read_text(encoding="utf-8"))
    with (folder / "encode.log").open("w", encoding="utf-8") as log, (folder / "records.jsonl").open("w", encoding="utf-8") as output:
        encoder = subprocess.Popen([str(args.vegeta), "encode", "-to=json", str(raw)],
                                   stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8")
        try:
            audit = audit_records((json.loads(line) for line in encoder.stdout), pdfs, output)
            if encoder.wait() != 0:
                raise RuntimeError("Incomplete or invalid Vegeta binary")
        finally:
            encoder.stdout.close()
            if encoder.poll() is None:
                encoder.terminate()
                encoder.wait()
    metrics = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    execution = json.loads((folder / "execution.json").read_text(encoding="utf-8"))
    summary = dict(metrics=normalize_metrics(metrics), audit=audit,
                   aborted=execution["aborted"], exit_code=execution["exit_code"],
                   cache_start="COLD: empty isolated DB, no PDF preload; workers newly started",
                   recovered_report=True)
    (folder / "summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    with raw.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    compressed = raw.with_suffix(".bin.gz")
    with raw.open("rb") as source, gzip.open(compressed, "wb") as output:
        shutil.copyfileobj(source, output)
    with gzip.open(compressed, "rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == digest
    (folder / "raw-artifact.json").write_text(json.dumps(dict(file=compressed.name,
        uncompressed_bytes=raw.stat().st_size, compressed_bytes=compressed.stat().st_size,
        uncompressed_sha256=digest), indent=2)+"\n", encoding="utf-8")
    raw.unlink()  # Verified compressed evidence replaces only its own raw duplicate.
    print(json.dumps({key: value for key, value in summary.items() if key != "audit"}, indent=2))
    print(json.dumps({key: value for key, value in audit.items() if key != "errors"}, indent=2))


if __name__ == "__main__":
    main()
