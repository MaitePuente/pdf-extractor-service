"""Official Windows Vegeta run: four external PDFs, Traefik, isolated empty Redis DB."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request

import pymupdf

from report import audit_records, normalize_metrics

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app.markdown import to_markdown

COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.traefik.yaml"]
PATTERNS = ["2020-Scrum-Guide-Spanish-Latin-South-*.pdf",
            "scrum_manager_historias_usuario.pdf", "Essential-Kanban-Condensed-Spanish.pdf",
            "Filosofia Lean.pdf"]


def discover_pdfs(directory):
    pdfs = []
    for pattern in PATTERNS:
        matches = list(directory.glob(pattern))
        if len(matches) != 1:
            raise RuntimeError(f"Require exactly one external PDF matching {pattern}: {matches}")
        path = matches[0].resolve()
        if path.is_relative_to(ROOT):
            raise RuntimeError("Keep the official PDFs outside this repository")
        body = path.read_bytes()
        if not body.startswith(b"%PDF"):
            raise RuntimeError(f"Invalid PDF signature: {path}")
        with pymupdf.open(stream=body, filetype="pdf") as document:
            if document.needs_pass:
                raise RuntimeError(f"Password-protected PDF: {path}")
            content = to_markdown(document)
            pdfs.append(dict(name=path.name, path=str(path), bytes=len(body),
                             page_count=document.page_count, sha256=hashlib.sha256(body).hexdigest(),
                             content_characters=len(content),
                             content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest()))
    if len({pdf["sha256"] for pdf in pdfs}) != 4:
        raise RuntimeError("The four official PDFs must have distinct SHA-256 values")
    if len({pdf["bytes"] for pdf in pdfs}) != 4:
        raise RuntimeError("This audit identifies requests by size; PDF sizes must be distinct")
    return pdfs


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--vegeta", type=Path, default=Path("D:/herramientas/vegeta/vegeta.exe"))
    parser.add_argument("--name", required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--redis-db", type=int, default=15, choices=range(1, 16))
    parser.add_argument("--results", type=Path, default=ROOT / "tests/stress/results")
    parser.add_argument("--inspect-only", action="store_true", help="Only inspect the four external PDFs")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        parser.error("Use a simple unique run name")
    pdfs = discover_pdfs(args.pdf_dir.resolve())
    if args.inspect_only:
        print(json.dumps(pdfs, ensure_ascii=False, indent=2))
        return
    destination = args.results.resolve() / args.name
    if not destination.is_relative_to(ROOT):
        parser.error("Evidence must stay inside this repository")
    if destination.exists():
        parser.error("Evidence directory already exists; choose another name")
    if not args.vegeta.is_file():
        parser.error("Vegeta executable not found")
    if subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip() != "main":
        parser.error("Run only on main")
    commands = []

    def command(argv, *, env=None, output=None, timeout=180):
        commands.append(argv)
        completed = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if output:
            (destination / output).write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"Command failed ({completed.returncode}): {argv}: {completed.stderr}")
        return completed.stdout.strip()

    def states(ids=None):
        ids = ids or command(COMPOSE + ["ps", "-q"]).splitlines()
        if not ids:
            raise RuntimeError("Docker project has no running containers")
        return json.loads(command(["docker", "inspect", *ids], timeout=15))

    def redis(*parts, db=0):
        return command(COMPOSE + ["exec", "-T", "redis", "redis-cli", "--raw", "-n", str(db), *parts])

    def save(name, value):
        (destination / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def replicas(containers):
        return [c for c in containers if c["Config"]["Labels"]["com.docker.compose.service"] == "extractor"]

    def require_config(containers, db):
        apis = replicas(containers)
        if len(apis) != 2 or len(containers) != 4:
            raise RuntimeError("Require exactly two APIs, Redis and Traefik in this Compose project")
        if any(c["State"].get("Health", {}).get("Status") != "healthy" for c in containers):
            raise RuntimeError("All four containers must be healthy before load")
        for api in apis:
            if api["HostConfig"]["Memory"] != 768*1024*1024 or api["HostConfig"]["NanoCpus"] != 1_000_000_000:
                raise RuntimeError("Unexpected extractor resource limits")
            if api["HostConfig"].get("PortBindings"):
                raise RuntimeError("Extractor must not expose a direct host port")
            if not {"CACHE_ENABLED=true", f"REDIS_URL=redis://redis:6379/{db}"}.issubset(api["Config"]["Env"]):
                raise RuntimeError("Unexpected cache configuration")
        return apis

    initial = states()
    require_config(initial, 0)
    if redis("DBSIZE", db=args.redis_db) != "0":
        raise RuntimeError(f"Redis DB {args.redis_db} is not empty; select another empty DB, never FLUSH")
    destination.mkdir(parents=True)
    save("pdfs.json", pdfs)
    save("initial-containers.json", initial)
    versions = dict(vegeta=command([str(args.vegeta), "-version"]), python=sys.version,
                    pymupdf=pymupdf.VersionBind, host=platform.platform(), host_cpu_threads=os.cpu_count(),
                    docker=command(["docker", "version", "--format", "{{.Server.Version}}"]),
                    compose=command(["docker", "compose", "version"]),
                    docker_resources=command(["docker", "info", "--format", "CPUs={{.NCPU}} Memory={{.MemTotal}}"]),
                    normal_db_initial_keys=int(redis("DBSIZE")), benchmark_db=args.redis_db)
    save("environment.json", versions)
    benchmark_env = os.environ.copy()
    benchmark_env["EXTRACTOR_BENCHMARK_REDIS_DB"] = str(args.redis_db)
    overlay = COMPOSE + ["-f", "compose.cache-benchmark.yaml"]
    up = ["up", "-d", "--no-deps", "--no-build", "--scale", "extractor=2",
          "--wait", "--wait-timeout", "150", "extractor"]
    started = None
    abort = None
    restored = False
    try:
        command(overlay + up, env=benchmark_env, output="isolated-up.log")
        isolated = states()
        apis = require_config(isolated, args.redis_db)
        isolated_ids = [c["Id"] for c in isolated]
        save("benchmark-containers.json", isolated)
        assert {c["Image"] for c in apis} == {c["Image"] for c in replicas(initial)}
        assert redis("DBSIZE", db=args.redis_db) == "0", "Benchmark DB must start empty"
        assert all(redis("EXISTS", "extract:v4:"+pdf["sha256"], db=args.redis_db) == "0" for pdf in pdfs)
        address = command(COMPOSE + ["port", "traefik", "80"])
        base = "http://127.0.0.1:" + address.rsplit(":", 1)[1]
        rule = apis[0]["Config"]["Labels"]["traefik.http.routers.pdf-markdown-extractor.rule"]
        host = rule.split(chr(96))[1]
        checks = []
        health_since = datetime.now(timezone.utc).isoformat()
        for number in range(6):
            audit = f"{args.name}-health-{number}"
            request = urllib.request.Request(base+"/health", headers={"Host": host, "X-Audit-Id": audit})
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.load(response)
                assert response.status == 200 and body == {"status": "ok", "service": "extractor"}
                checks.append(dict(audit_id=audit, status=response.status, body=body))
        proxy = next(c for c in isolated if c["Config"]["Labels"]["com.docker.compose.service"] == "traefik")
        logs = command(["docker", "logs", "--since", health_since, proxy["Id"]])
        health_logs = []
        for line in logs.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("request_X-Audit-Id", "")).startswith(args.name+"-health-"):
                health_logs.append(row)
        servers = {c["NetworkSettings"]["Networks"]["pdf-network"]["IPAddress"]+":8000": c["Name"].lstrip("/") for c in apis}
        distribution = Counter(row.get("ServiceAddr") for row in health_logs)
        assert set(distribution) == set(servers) and len(health_logs) == 6, "Pre-load balance evidence is incomplete"
        save("health-before.json", dict(url=base, checks=checks, logs=health_logs, distribution=dict(distribution)))
        targets = "\n\n".join(f"POST {base}/extract\nHost: {host}\nContent-Type: application/pdf\nAccept-Encoding: identity\nX-Audit-Id: {args.name}-pdf-{index+1}\n@{pdf['path']}" for index, pdf in enumerate(pdfs)) + "\n"
        (destination / "targets.http").write_text(targets, encoding="utf-8", newline="\n")
        raw = destination / "results.bin"
        attack = [str(args.vegeta), "attack", "-rate=50/s", "-duration=30s", "-timeout=30s",
                  "-format=http", "-max-body=-1", "-name="+args.name,
                  "-targets="+str(destination / "targets.http"), "-output="+str(raw)]
        commands.append(attack)
        started = datetime.now(timezone.utc).isoformat()
        samples, abort = [], None
        began = time.perf_counter()
        print(json.dumps(dict(started_utc=started, command=attack, cache="COLD DB; no preload")), flush=True)
        with (destination / "attack.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(attack, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    try:
                        live = states(isolated_ids)
                    except (RuntimeError, subprocess.TimeoutExpired) as exc:
                        try:
                            command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
                        except (RuntimeError, subprocess.TimeoutExpired):
                            abort = "Docker unavailable: " + str(exc)
                            process.terminate()
                            break
                        samples.append(dict(elapsed_s=time.perf_counter()-began, telemetry_error=str(exc)))
                        time.sleep(1)
                        continue
                    try:
                        stats = command(["docker", "stats", "--no-stream", "--format", "{{json .}}",
                                         *[c["Id"] for c in live]], timeout=15)
                    except (RuntimeError, subprocess.TimeoutExpired) as exc:
                        stats = ""
                        samples.append(dict(elapsed_s=time.perf_counter()-began, telemetry_error=str(exc)))
                    samples.append(dict(elapsed_s=time.perf_counter()-began,
                                        states=[dict(name=c["Name"], state=c["State"]) for c in live],
                                        stats=stats))
                    if any(c["State"].get("OOMKilled") for c in live):
                        abort = "Severe OOM in a project container"
                        process.terminate()
                        break
                    time.sleep(1)
                code = process.wait()
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
        save("execution.json", dict(started_utc=started, command=attack, exit_code=code,
                                    aborted=abort, wall_seconds=time.perf_counter()-began, samples=samples))
        save("after-load-containers.json", states(isolated_ids))
        # Save volatile server evidence before decoding can fail or API restoration removes containers.
        proxy_log = command(["docker", "logs", "--since", started, proxy["Id"]], output="traefik.log")
        api_logs = {api["Id"]: command(["docker", "logs", "--since", started, api["Id"]],
                                       output=f"extractor-{index}.log")
                    for index, api in enumerate(apis, 1)}
        save("commands.json", commands)
        metrics = json.loads(command([str(args.vegeta), "report", "-type=json", str(raw)], output="report.json"))
        command([str(args.vegeta), "report", str(raw)], output="report.txt")
        encode_command = [str(args.vegeta), "encode", "-to=json", str(raw)]
        commands.append(encode_command)
        with (destination / "encode.log").open("w", encoding="utf-8") as log, (destination / "records.jsonl").open("w", encoding="utf-8") as output:
            encoder = subprocess.Popen(encode_command, stdout=subprocess.PIPE, stderr=log,
                                       text=True, encoding="utf-8")
            try:
                audit = audit_records((json.loads(line) for line in encoder.stdout), pdfs, output)
                if encoder.wait() != 0:
                    raise RuntimeError("Could not decode Vegeta evidence")
            finally:
                encoder.stdout.close()
                if encoder.poll() is None:
                    encoder.terminate()
                    encoder.wait()
        access = []
        logs = proxy_log
        for line in logs.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("request_X-Audit-Id", "")).startswith(args.name+"-pdf-"):
                access.append(row)
        with (destination / "traefik-access.jsonl").open("w", encoding="utf-8") as output:
            for row in access:
                output.write(json.dumps(row)+"\n")
        balance = Counter(servers.get(row.get("ServiceAddr"), "UNKNOWN") for row in access)
        profiles = []
        for index, api in enumerate(apis, 1):
            messages = api_logs[api["Id"]]
            for line in messages.splitlines():
                if "PROFILE " in line:
                    row = json.loads(line.split("PROFILE ", 1)[1])
                    if row.get("audit_id", "").startswith(args.name+"-pdf-"):
                        row["replica"] = api["Name"].lstrip("/")
                        profiles.append(row)
        save("profiles.json", profiles)
        post = states(isolated_ids)
        save("after-load-containers.json", post)
        summary = dict(metrics=normalize_metrics(metrics), audit=audit,
                       cache_start="COLD: empty isolated DB, no PDF preload; workers newly started",
                       cache_db=args.redis_db, balance=dict(balance), traefik_access_records=len(access),
                       traefik_requests_by_pdf=dict(Counter(row["request_X-Audit-Id"] for row in access)),
                       final_health={c["Name"]: c["State"].get("Health", {}).get("Status") for c in post},
                       aborted=abort, exit_code=code)
        save("summary.json", summary)
        with raw.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        compressed = raw.with_suffix(".bin.gz")
        with raw.open("rb") as source, gzip.open(compressed, "wb") as output:
            shutil.copyfileobj(source, output)
        with gzip.open(compressed, "rb") as source:
            assert hashlib.file_digest(source, "sha256").hexdigest() == digest
        save("raw-artifact.json", dict(file=compressed.name, uncompressed_bytes=raw.stat().st_size,
                                       compressed_bytes=compressed.stat().st_size, uncompressed_sha256=digest))
        raw.unlink()  # Only this run's verified, compressed duplicate.
        for pdf in pdfs:
            assert hashlib.sha256(Path(pdf["path"]).read_bytes()).hexdigest() == pdf["sha256"]
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        restarted = []
        for original in initial:
            if original in replicas(initial):
                continue
            current = json.loads(command(["docker", "inspect", original["Id"]]))[0]
            if not current["State"]["Running"]:
                save(original["Config"]["Labels"]["com.docker.compose.service"]+"-failure.json", current)
                command(["docker", "start", original["Id"]])
                restarted.append(original["Name"])
        deadline = time.monotonic()+120
        while True:
            infrastructure = states([c["Id"] for c in initial if c not in replicas(initial)])
            if all(c["State"].get("Health", {}).get("Status") == "healthy" for c in infrastructure):
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Could not recover existing infrastructure after load")
            time.sleep(1)
        command(COMPOSE + up, output="restore-up.log")
        final = states()
        require_config(final, 0)
        for original, current in zip(sorted(replicas(initial), key=lambda c: c["Name"]),
                                     sorted(replicas(final), key=lambda c: c["Name"])):
            assert current["Image"] == original["Image"], "Extractor image changed"
            assert sorted(current["Config"]["Env"]) == sorted(original["Config"]["Env"]), "Extractor environment was not restored"
        restored = True
        save("restored-containers.json", final)
        save("restoration.json", dict(restored=restored, normal_db_keys=int(redis("DBSIZE")),
                                      benchmark_db_keys=int(redis("DBSIZE", db=args.redis_db)),
                                      infrastructure_restarted=restarted,
                                      infrastructure_unchanged=all(
                                          any(c["Id"] == original["Id"] and c["State"]["StartedAt"] == original["State"]["StartedAt"] for c in final)
                                          for original in initial if original not in replicas(initial))))
        save("commands.json", commands)
    if abort:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
