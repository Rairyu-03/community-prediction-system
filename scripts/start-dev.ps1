$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $workspaceRoot "backend"
$frontendRoot = Join-Path $workspaceRoot "frontend"
$pythonPath = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
$viteEntry = Join-Path $frontendRoot "node_modules\vite\bin\vite.js"
$pidFile = Join-Path $workspaceRoot "runtime\dev-pids.json"

if (Test-Path -LiteralPath $pidFile) {
    $existingIds = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    $runningIds = @($existingIds.backend, $existingIds.frontend) | Where-Object {
        $_ -and (Get-Process -Id $_ -ErrorAction SilentlyContinue)
    }
    if ($runningIds.Count -eq 2) {
        Write-Host "Development services are already running."
        return
    }
    foreach ($runningId in $runningIds) {
        Stop-Process -Id $runningId -Force
    }
    Remove-Item -LiteralPath $pidFile -Force
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw ".venv was not found. Install the Python dependencies first."
}
if (-not (Test-Path -LiteralPath $viteEntry)) {
    throw "Vite was not found. Install the frontend dependencies first."
}

$nodeCommand = Get-Command node.exe -ErrorAction Stop
New-Item -ItemType Directory -Force -Path (Split-Path $pidFile) | Out-Null

$backendProcess = Start-Process -FilePath $pythonPath `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload", "--reload-dir", $backendRoot `
    -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru

$frontendProcess = Start-Process -FilePath $nodeCommand.Source `
    -ArgumentList $viteEntry, "--host", "0.0.0.0", "--port", "5173" `
    -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru

@{
    backend = $backendProcess.Id
    frontend = $frontendProcess.Id
    startedAt = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8

Write-Host "Development services started:"
Write-Host "  Frontend: http://127.0.0.1:5173"
Write-Host "  Backend:  http://127.0.0.1:8000/docs"
Write-Host "Stop: powershell -ExecutionPolicy Bypass -File scripts/stop-dev.ps1"
