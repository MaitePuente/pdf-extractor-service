"""Run k6 through the current development Traefik and retain resource evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import threading
import urllib.request


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--cache", choices=["BYPASS", "HIT", "MISS"], required=True)
    parser.add_argument("--vus", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=1, help="Iterations per VU")
    parser.add_argument("--sha256", default="")
    parser.add_argument("--timeout", help="HTTP timeout: defaults to 5s for HIT, 1800s for conversion")
    parser.add_argument("--results", type=Path, help="Separate evidence directory; default preserves baseline location")
    parser.add_argument("--probe-health", action="store_true", help="Sample /health through Traefik during this diagnostic run")
    parser.add_argument("--spike", action="store_true")
    parser.add_argument("--diagnostic", action="store_true", help="Allow ONE request to finish despite failed health checks; never bypass OOM protection")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name) or args.vus < 1 or args.iterations < 1:
        parser.error("Use a simple run name and positive VUs/iterations")
    if args.diagnostic and (args.spike or args.vus != 1 or args.iterations != 1):
        parser.error("Diagnostic mode permits only 1 VU and 1 iteration")
    service = Path(__file__).resolve().parents[2]
    results = (args.results.resolve() if args.results else
               service.parents[1] / "tests/stress/results/extractor-baseline")
    results.mkdir(parents=True, exist_ok=True)
    os.chdir(service)
    compose = ["compose", "-f", "compose.yaml", "-f", "compose.traefik.yaml"]
    port = docker(*compose, "port", "traefik", "80").rsplit(":", 1)[1]
    ids = docker("ps", "-q", "--filter", "label=com.docker.compose.project=pdf-extractor").splitlines()
    if not ids:
        raise RuntimeError("No running extractor project containers")
    initial = json.loads(docker("inspect", *ids))
    if any(c["State"].get("Health", {}).get("Status") != "healthy" for c in initial):
        raise RuntimeError("All project containers must be healthy before starting k6")
    summary = results / f"{args.name}.summary.json"
    if any((results / f"{args.name}.{suffix}").exists() for suffix in ["log", "summary.json", "resources.json"]):
        parser.error("Run name already exists; choose a new name to preserve previous evidence")
    env = os.environ.copy()
    env.update(PDF_PATH=str(Path(args.pdf).resolve()), EXTRACT_URL=f"http://localhost:{port}/extract",
               EXPECT_CACHE=args.cache, VUS=str(args.vus), ITERATIONS_PER_VU=str(args.iterations),
               EXPECTED_CONTENT_SHA256=args.sha256, RUN_ID=args.name, RESULT_FILE=str(summary),
               REQUEST_TIMEOUT=args.timeout or ("5s" if args.cache == "HIT" else "1800s"))
    script = "spike.js" if args.spike else "baseline.js"
    command = ["k6", "run", "--no-color", "--log-format", "json", str(service / "tests/performance" / script)]
    start = time.time()
    samples = []
    aborted = None
    health_failures = set()
    health_samples = []
    stop_health = threading.Event()

    def probe_health():
        number = 0
        while not stop_health.is_set():
            began = time.perf_counter()
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/health",
                headers={"Host": "localhost", "X-Audit-Id": f"{args.name}-health-{number}"},
            )
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    row = {"status": response.status, "body": json.load(response)}
            except Exception as exc:
                row = {"error": repr(exc)}
            row.update(audit_id=f"{args.name}-health-{number}",
                       elapsed_s=time.time() - start,
                       duration_ms=(time.perf_counter() - began) * 1000)
            health_samples.append(row)
            number += 1
            stop_health.wait(0.05)

    health_thread = None
    if args.probe_health:
        health_thread = threading.Thread(target=probe_health, daemon=True)
        health_thread.start()
    with (results / f"{args.name}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            raw = docker("stats", "--no-stream", "--format", "{{json .}}")
            sample = {"elapsed_s": round(time.time() - start, 3),
                      "containers": [json.loads(line) for line in raw.splitlines() if line]}
            samples.append(sample)
            states = json.loads(docker("inspect", *ids))
            for container in states:
                state = container["State"]
                unhealthy = state.get("Health", {}).get("Status") == "unhealthy"
                if unhealthy:
                    health_failures.add(container["Name"])
                if state.get("OOMKilled") or not state["Running"] or (unhealthy and not args.diagnostic):
                    aborted = f"Unsafe container state: {container['Name']} {state}"
                    process.terminate()
                    break
            if aborted:
                break
            time.sleep(1)
        code = process.wait()
    stop_health.set()
    if health_thread is not None:
        health_thread.join(timeout=3)
    final = json.loads(docker("inspect", *ids))
    report = {"name": args.name, "command": command,
              "environment": {key: env[key] for key in ["PDF_PATH", "EXTRACT_URL", "EXPECT_CACHE", "VUS", "ITERATIONS_PER_VU", "EXPECTED_CONTENT_SHA256", "REQUEST_TIMEOUT"]},
              "exit_code": code, "wall_seconds": time.time() - start, "aborted": aborted,
              "health_failures": sorted(health_failures),
              "health_samples": health_samples,
              "containers": [{"name": c["Name"], "id": c["Id"], "networks": c["NetworkSettings"]["Networks"]} for c in initial],
              "samples": samples,
              "final_states": [{"name": c["Name"], "state": c["State"], "restarts": c["RestartCount"]} for c in final]}
    (results / f"{args.name}.resources.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"name": args.name, "exit_code": code, "wall_seconds": report["wall_seconds"], "aborted": aborted,
                      "summary": str(summary), "samples": len(samples)}))
    if summary.exists():
        metrics = json.loads(summary.read_text(encoding="utf-8"))["metrics"]
        print(json.dumps({key: metrics[key]["values"] for key in [
            "http_req_duration", "http_req_sending", "http_req_waiting", "http_req_receiving",
            "http_req_failed", "extract_errors", "http_reqs"] if key in metrics}))
    else:
        print((results / f"{args.name}.log").read_text(encoding="utf-8")[-2500:])
    if aborted:
        raise SystemExit(2)
    # A failed latency threshold (k6 exit 99) is retained as a measurement, not hidden.
    raise SystemExit(code)


if __name__ == "__main__":
    main()
