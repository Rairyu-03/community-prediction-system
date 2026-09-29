$ErrorActionPreference = "Stop"

try {
    $workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $pythonPath = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
    $requirementsPath = Join-Path $workspaceRoot "backend\requirements-dev.txt"
    $frontendRoot = Join-Path $workspaceRoot "frontend"
    $startScript = Join-Path $PSScriptRoot "start-dev.ps1"
    $stopScript = Join-Path $PSScriptRoot "stop-dev.ps1"

    Write-Host "=================================================="
    Write-Host "  Community Prediction System Launcher"
    Write-Host "=================================================="
    Write-Host ""

    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host "[1/4] Creating the Python virtual environment..."
        $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
        $pythonArguments = @()
        if (-not $systemPython) {
            $systemPython = Get-Command py.exe -ErrorAction SilentlyContinue
            $pythonArguments = @("-3")
        }
        if (-not $systemPython) {
            throw "Python was not found. Install Python 3.11 or later and add it to PATH."
        }
        & $systemPython.Source @pythonArguments -m venv (Join-Path $workspaceRoot ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the Python virtual environment."
        }
    }
    else {
        Write-Host "[1/4] Python environment is ready."
    }

    Write-Host "[2/4] Verifying Python dependencies..."
    & $pythonPath -m pip install --disable-pip-version-check -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Python dependencies. Check the network or pip configuration."
    }

    $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if (-not $pnpmCommand) {
        $corepackCommand = Get-Command corepack.cmd -ErrorAction SilentlyContinue
        if (-not $corepackCommand) {
            throw "Node.js/Corepack was not found. Install Node.js 20 or later."
        }
        Write-Host "[3/4] Enabling pnpm..."
        & $corepackCommand.Source enable | Out-Null
        $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
        if (-not $pnpmCommand) {
            throw "pnpm is unavailable. Open a terminal as administrator and run: corepack enable"
        }
    }

    Write-Host "[3/4] Verifying frontend dependencies..."
    Push-Location $frontendRoot
    try {
        & $pnpmCommand.Source install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install frontend dependencies."
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "[4/4] Starting the frontend and backend..."
    & $startScript

    Write-Host "Waiting for the web page..."
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $frontendResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5173" -TimeoutSec 2
            $backendResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
            if ($frontendResponse.StatusCode -eq 200 -and $backendResponse.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) {
        throw "The page was not ready in 30 seconds. Check whether ports 5173 and 8000 are occupied, then run scripts\stop-dev.ps1 and retry."
    }

    if ($env:COMMUNITY_NO_BROWSER -ne "1") {
        Start-Process "http://127.0.0.1:5173"
    }

    Write-Host ""
    Write-Host "Started successfully." -ForegroundColor Green
    Write-Host "  Application: http://127.0.0.1:5173"
    Write-Host "  API docs:    http://127.0.0.1:8000/docs"
    Write-Host "  Stop:        scripts\stop-dev.ps1"
    Start-Sleep -Seconds 2
}
catch {
    if ($stopScript -and (Test-Path -LiteralPath (Join-Path $workspaceRoot "runtime\dev-pids.json"))) {
        & $stopScript
    }
    Write-Host ""
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
