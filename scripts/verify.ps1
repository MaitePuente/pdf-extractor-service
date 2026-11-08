param(
    [string]$BaseUrl,
    [string]$PdfPath
)

$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not $BaseUrl) {
        $published = docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
        if ($LASTEXITCODE -ne 0 -or -not $published) { throw 'Traefik has no published HTTP port.' }
        $port = ($published | Select-Object -First 1).Split(':')[-1]
        $BaseUrl = "http://localhost:$port"
    }
    $BaseUrl = $BaseUrl.TrimEnd('/')

    foreach ($route in @('/health', '/health/ready')) {
        $response = Invoke-WebRequest -Uri "$BaseUrl$route" -TimeoutSec 10
        if ($response.StatusCode -ne 200) { throw "$route returned $($response.StatusCode)." }
        Write-Output "$route HTTP $($response.StatusCode)"
    }

    if ($PdfPath) {
        $pdf = (Resolve-Path -LiteralPath $PdfPath).Path
        $response = Invoke-WebRequest -Uri "$BaseUrl/extract" -Method Post `
            -ContentType 'application/pdf' -Body ([System.IO.File]::ReadAllBytes($pdf)) `
            -TimeoutSec 60
        $result = $response.Content | ConvertFrom-Json
        if ($response.StatusCode -ne 200 -or $null -eq $result.content -or $result.page_count -lt 1) {
            throw 'Unexpected POST /extract response.'
        }
        Write-Output "POST /extract HTTP 200; pages=$($result.page_count); X-Cache=$($response.Headers['X-Cache'])"
    }
} finally {
    Pop-Location
}
