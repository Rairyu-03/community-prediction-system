$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidFile = Join-Path $workspaceRoot "runtime\dev-pids.json"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "No development service PID file was found."
    exit 0
}

$processIds = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
foreach ($processId in @($processIds.backend, $processIds.frontend)) {
    if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $processId -Force
    }
}

# A virtual-environment launcher or Vite may leave a child process listening
# after its parent exits. Limit cleanup to commands started from this workspace.
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($workspaceRoot) -and
    ($_.CommandLine.Contains("uvicorn") -or $_.CommandLine.Contains("vite"))
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath $pidFile -Force
Write-Host "Development services stopped."
