$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker is not installed or not in PATH.' }
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop / Docker Engine first.' }
    docker compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
    $network = docker network ls --filter 'name=^pdf-network$' --format '{{.Name}}'
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Docker networks.' }
    if ($network -notcontains 'pdf-network') {
        docker network create pdf-network
        if ($LASTEXITCODE -ne 0) { throw 'Could not create pdf-network.' }
    }
    docker compose -f compose.yaml -f compose.traefik.yaml up --build -d --scale extractor=2 --wait --wait-timeout 150
    if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed; inspect docker compose logs.' }
    $published = docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
    if ($LASTEXITCODE -ne 0 -or -not $published) { throw 'Traefik port was not published.' }
    $port = ($published | Select-Object -First 1).Split(':')[-1]
    Write-Host "Health: http://localhost:$port/health"
    Write-Host "Extract: http://localhost:$port/extract"
    Write-Host "Swagger (DOCS_ENABLED=true): http://localhost:$port/docs"
    Write-Host "ReDoc: http://localhost:$port/redoc | OpenAPI: http://localhost:$port/openapi.json"
} finally {
    Pop-Location
}
