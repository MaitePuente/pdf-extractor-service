"""Functional verification only: one large PDF twice, no timing benchmark."""
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import urllib.request

import pymupdf

ROOT = Path.cwd()
OUT = Path(__file__).parent
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.traefik.yaml"]


def command(*args):
    return subprocess.check_output(args, text=True, encoding="utf-8").strip()


port = command(*COMPOSE, "port", "traefik", "80").rsplit(":", 1)[1]
base = f"http://localhost:{port}"
report = {"url": base, "purpose": "functional, no comparative timings"}
for route in ("health", "docs", "redoc", "openapi.json"):
    with urllib.request.urlopen(f"{base}/{route}", timeout=10) as response:
        report[route] = response.status
ids = command(*COMPOSE, "ps", "-q", "extractor").splitlines()
report["replicas"] = []
probe = "import os,sys,shutil,importlib.util,json; print(json.dumps(dict(uid=os.getuid(),python=sys.version,shell=shutil.which('sh'),pip=shutil.which('pip'),pip_module=importlib.util.find_spec('pip') is not None,uv=shutil.which('uv'),readonly=bool(os.statvfs('/service').f_flag & os.ST_RDONLY),proc_status=open('/proc/1/status').read())))"
for cid in ids:
    info = json.loads(command("docker", "inspect", cid))[0]
    report["replicas"].append({
        "name": info["Name"], "health": info["State"]["Health"]["Status"], "oom": info["State"]["OOMKilled"],
        "security_opt": info["HostConfig"]["SecurityOpt"], "cap_drop": info["HostConfig"]["CapDrop"],
        "read_only": info["HostConfig"]["ReadonlyRootfs"], "memory": info["HostConfig"]["Memory"], "nano_cpus": info["HostConfig"]["NanoCpus"],
        "whoami": command("docker", "exec", cid, "whoami"), "id": command("docker", "exec", cid, "id"),
        "runtime": json.loads(command("docker", "exec", cid, "python", "-c", probe)),
        "global_pip": command("docker", "exec", cid, "/usr/local/bin/python", "-c", "import importlib.util; print(importlib.util.find_spec('pip'))"),
    })
pdf = Path(r"D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf")
body = pdf.read_bytes()
with pymupdf.open(stream=body, filetype="pdf") as document:
    pages = document.page_count
report["pdf"] = {"path": str(pdf), "bytes": len(body), "page_count": pages, "sha256": hashlib.sha256(body).hexdigest()}
assert len(body) == 17749468 and pages == 279
assert report["pdf"]["sha256"] == "728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9b55b8343b39c005713162"
report["responses"] = []
for number in range(2):
    request = urllib.request.Request(base + "/extract", data=body, headers={"Content-Type": "application/pdf", "X-Audit-Id": f"architecture-functional-{number}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
        value = {"status": response.status, "cache": response.headers.get("X-Cache"), "audit": response.headers.get("X-Audit-Id"), "pages": payload["page_count"], "characters": len(payload["content"]), "text_sha256": hashlib.sha256(payload["content"].encode()).hexdigest()}
        report["responses"].append(value)
        assert value["pages"] == 279 and value["characters"] == 427008
        assert value["text_sha256"] == "c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc"
# Declared overflow: do not actually send 20 MiB to exercise early rejection.
(OUT / "runtime.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
connection = http.client.HTTPConnection("localhost", int(port), timeout=10)
connection.putrequest("POST", "/extract")
connection.putheader("Content-Type", "application/pdf")
connection.putheader("Content-Length", str(20 * 1024 * 1024 + 1))
connection.putheader("Expect", "100-continue")
connection.putheader("Connection", "close")
connection.endheaders()
response = connection.getresponse()
report["oversized_declared"] = {"status": response.status, "body": response.read().decode()}
connection.close()
assert response.status == 413
(OUT / "runtime.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
