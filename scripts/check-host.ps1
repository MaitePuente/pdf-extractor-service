param([string]$OutputPath)
$ErrorActionPreference = 'Stop'
$samples = @()
1..3 | ForEach-Object {
    $memory = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
    $cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor | Where-Object Name -eq '_Total'
    $samples += [pscustomobject]@{
        timestamp = (Get-Date).ToUniversalTime().ToString('o')
        available_mib = [long]$memory.AvailableMBytes
        committed_percent = [long]$memory.PercentCommittedBytesInUse
        pages_per_second = [long]$memory.PagesPersec
        page_reads_per_second = [long]$memory.PageReadsPersec
        cpu_percent = [long]$cpu.PercentProcessorTime
    }
    Start-Sleep -Seconds 1
}
# Conservative comparison gate, not a universal definition of host health.
# Page reads are disk activity; pages/sec alone also includes other paging.
$lowMemory = @($samples | Where-Object available_mib -lt 1024).Count -gt 0
$severePaging = @($samples | Where-Object page_reads_per_second -gt 100).Count -ge 2
$result = [pscustomobject]@{
    stable_for_comparison = (-not $lowMemory -and -not $severePaging)
    policy = 'All samples >=1024 MiB available; fewer than 2 samples >100 page reads/s'
    samples = $samples
}
$json = $result | ConvertTo-Json -Depth 5
if ($OutputPath) { [IO.File]::WriteAllText($OutputPath, $json, [Text.UTF8Encoding]::new($false)) }
Write-Output $json
if (-not $result.stable_for_comparison) {
    Write-Warning 'entorno no suficientemente estable para comparar'
    exit 2
}
