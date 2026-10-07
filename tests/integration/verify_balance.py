"""Verify the development proxy using HTTP responses and real Traefik logs.

Run explicitly: uv run --locked python tests/integration/verify_balance.py --replicas 2
Optional --stop-one stops and restores one extractor owned by this Compose project.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid

import pymupdf


ROOT = Path(__file__).resolve().parents[2]


def command(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def compose(*args):
    return command("docker", "compose", "-f", "compose.yaml", "-f", "compose.traefik.yaml", *args)


def inspect_replicas():
    ids = compose("ps", "-q", "extractor").splitlines()
    return json.loads(command("docker", "inspect", *ids))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replicas", type=int, required=True, choices=range(2, 6))
    parser.add_argument("--stop-one", action="store_true")
    args = parser.parse_args()
    replicas = inspect_replicas()
    assert len(replicas) == args.replicas
    assert all(c["State"]["Health"]["Status"] == "healthy" for c in replicas)
    servers = {
        c["NetworkSettings"]["Networks"]["pdf-network"]["IPAddress"] + ":8000": c["Name"].lstrip("/")
        for c in replicas
    }
    assert all(c["HostConfig"]["NanoCpus"] == 1000000000 for c in replicas)
    assert all(c["HostConfig"]["Memory"] == 768 * 1024 * 1024 for c in replicas)
    assert all(not c["HostConfig"].get("PortBindings") for c in replicas)
    assert all("REDIS_URL=redis://redis:6379/0" in c["Config"]["Env"] for c in replicas)
    address = compose("port", "traefik", "80")
    base_url = "http://localhost:" + address.rsplit(":", 1)[1]
    token = uuid.uuid4().hex
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 100), "Shared cache " + token)
        body = doc.tobytes()
    key = "extract:v1:" + hashlib.sha256(body).hexdigest()
    compose("exec", "-T", "redis", "redis-cli", "DEL", key)
    observed = {}
    stopped = None

    def request(index, path="/extract", data=body):
        audit_id = token + "-" + str(index)
        req = urllib.request.Request(
            base_url + path, data=data,
            headers={"Content-Type": "application/pdf", "Host": os.environ.get("EXTRACTOR_HOST", "localhost"), "X-Audit-Id": audit_id},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            assert response.status == 200
            result = json.load(response)
            observed[audit_id] = {"status": response.status, "cache": response.headers.get("X-Cache")}
            return result

    try:
        first = request(0)
        assert set(first) == {"content", "page_count"} and first["page_count"] == 1
        assert token in first["content"]
        for index in range(1, args.replicas * 2):
            assert request(index) == first
        assert observed[token + "-0"]["cache"] == "MISS"
        assert all(r["cache"] == "HIT" for k, r in observed.items() if k != token + "-0")
        if args.stop_one:
            stopped = replicas[0]
            command("docker", "stop", stopped["Id"])
            # Docker provider events are throttled; allow route convergence.
            time.sleep(3)
            for index in range(args.replicas * 2, args.replicas * 4):
                assert request(index) == first
        records = {}
        for line in compose("logs", "--no-log-prefix", "traefik").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            audit_id = row.get("request_X-Audit-Id")
            if audit_id in observed:
                assert row["DownstreamStatus"] == 200
                records[audit_id] = servers[row["ServiceAddr"]]
        assert set(records) == set(observed), "Missing access log evidence"
        initial = {k: v for k, v in records.items() if int(k.rsplit("-", 1)[1]) < args.replicas * 2}
        assert set(initial.values()) == set(servers.values()), "Some replicas received no requests"
        if stopped:
            remaining = {v for k, v in records.items() if k not in initial}
            assert stopped["Name"].lstrip("/") not in remaining
            assert len(remaining) == args.replicas - 1
        print(json.dumps({
            "replicas": args.replicas, "url": base_url,
            "initial_distribution": dict(Counter(initial.values())),
            "stopped_replica": stopped["Name"] if stopped else None,
            "requests": [{"audit_id": k, "replica": records[k], **v} for k, v in observed.items()],
            "result": first,
        }, indent=2))
    finally:
        if stopped:
            command("docker", "start", stopped["Id"])
            deadline = time.monotonic() + 120
            while True:
                health = json.loads(command("docker", "inspect", stopped["Id"]))[0]["State"]["Health"]["Status"]
                if health == "healthy":
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("Restored replica did not become healthy")
                time.sleep(1)
        compose("exec", "-T", "redis", "redis-cli", "DEL", key)


if __name__ == "__main__":
    main()
