$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    docker compose -f compose.yaml -f compose.traefik.yaml stop
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the extractor stack.' }
} finally {
    Pop-Location
}
