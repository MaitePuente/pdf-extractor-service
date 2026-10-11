#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v docker >/dev/null 2>&1 || { echo 'Docker is not installed or not in PATH.' >&2; exit 1; }
docker info --format '{{.ServerVersion}}'
docker compose version
if ! docker network inspect pdf-network >/dev/null 2>&1; then
    docker network create pdf-network
fi
docker compose -f compose.yaml -f compose.traefik.yaml up --build -d --scale extractor=2 --wait --wait-timeout 150
published=$(docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80)
port=${published##*:}
test -n "$port"
printf 'Health: http://localhost:%s/health\nExtract: http://localhost:%s/extract\nSwagger (DOCS_ENABLED=true): http://localhost:%s/docs\nReDoc: http://localhost:%s/redoc\nOpenAPI: http://localhost:%s/openapi.json\n' "$port" "$port" "$port" "$port" "$port"
