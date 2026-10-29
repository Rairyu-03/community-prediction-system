param(
    [string]$PythonVersion = "3.13.14"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Child
    )
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $childFull = [System.IO.Path]::GetFullPath($Child)
    $prefix = $parentFull + [System.IO.Path]::DirectorySeparatorChar
    if (-not $childFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe output path: $childFull"
    }
}

try {
    $workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $frontendRoot = Join-Path $workspaceRoot "frontend"
    $backendRoot = Join-Path $workspaceRoot "backend"
    $requirementsPath = Join-Path $backendRoot "requirements.txt"
    $packageJsonPath = Join-Path $frontendRoot "package.json"
    $releaseRoot = Join-Path $workspaceRoot "release"
    $cacheRoot = Join-Path $workspaceRoot "build\portable-cache"

    $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $appVersion = [string]$packageJson.version
    if (-not $appVersion) {
        throw "frontend/package.json does not contain a version."
    }

    $packageName = "CommunityPredictionSystem-Portable-v$appVersion"
    $packageRoot = Join-Path $releaseRoot $packageName
    $zipPath = Join-Path $releaseRoot "$packageName.zip"
    $hashPath = "$zipPath.sha256.txt"
    Assert-ChildPath -Parent $releaseRoot -Child $packageRoot
    Assert-ChildPath -Parent $releaseRoot -Child $zipPath

    Write-Host "=================================================="
    Write-Host "  Portable package builder v$appVersion"
    Write-Host "=================================================="
    Write-Host ""

    Write-Host "[1/8] Checking the frontend build toolchain..."
    $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if (-not $pnpmCommand) {
        $corepackCommand = Get-Command corepack.cmd -ErrorAction SilentlyContinue
        if (-not $corepackCommand) {
            throw "Node.js 20 or later with Corepack is required on the build computer."
        }
        Invoke-Checked -FilePath $corepackCommand.Source -Arguments @("enable")
        $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
        if (-not $pnpmCommand) {
            throw "pnpm is unavailable. Run 'corepack enable' as administrator and retry."
        }
    }

    Write-Host "[2/8] Installing frontend dependencies and building the UI..."
    Push-Location $frontendRoot
    try {
        Invoke-Checked -FilePath $pnpmCommand.Source -Arguments @("install", "--frozen-lockfile")
        Invoke-Checked -FilePath $pnpmCommand.Source -Arguments @("run", "build")
    }
    finally {
        Pop-Location
    }

    New-Item -ItemType Directory -Force -Path $releaseRoot, $cacheRoot | Out-Null
    if (Test-Path -LiteralPath $packageRoot) {
        Remove-Item -LiteralPath $packageRoot -Recurse -Force
    }
    foreach ($oldFile in @($zipPath, $hashPath)) {
        if (Test-Path -LiteralPath $oldFile) {
            Remove-Item -LiteralPath $oldFile -Force
        }
    }
    New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null

    $pythonArchive = Join-Path $cacheRoot "python-$PythonVersion-embed-amd64.zip"
    $getPipPath = Join-Path $cacheRoot "get-pip.py"
    $pythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Write-Host "[3/8] Preparing the portable Python runtime..."
    if (-not (Test-Path -LiteralPath $pythonArchive)) {
        Write-Host "Downloading Python $PythonVersion..."
        Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonArchive
    }
    else {
        Write-Host "Reusing the cached Python $PythonVersion runtime."
    }
    if (-not (Test-Path -LiteralPath $getPipPath)) {
        Write-Host "Downloading the Python package installer..."
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath
    }

    Write-Host "[4/8] Assembling application files..."
    $portablePython = Join-Path $packageRoot "runtime\python"
    New-Item -ItemType Directory -Force -Path $portablePython | Out-Null
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath $portablePython -Force
    Copy-Item -LiteralPath (Join-Path $backendRoot "app") -Destination (Join-Path $packageRoot "backend\app") -Recurse -Force
    Copy-Item -LiteralPath $requirementsPath -Destination (Join-Path $packageRoot "backend\requirements.txt") -Force
    Copy-Item -LiteralPath (Join-Path $frontendRoot "dist") -Destination (Join-Path $packageRoot "frontend\dist") -Recurse -Force

    $pythonTag = (($PythonVersion -split '\.')[0..1] -join '')
    $pthPath = Join-Path $portablePython "python$pythonTag._pth"
    if (-not (Test-Path -LiteralPath $pthPath)) {
        throw "Embedded Python path file was not found: $pthPath"
    }
    @(
        "python$pythonTag.zip"
        "."
        "Lib\site-packages"
        "import site"
    ) | Set-Content -LiteralPath $pthPath -Encoding ASCII

    $sitePackages = Join-Path $portablePython "Lib\site-packages"
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
    $embeddedPython = Join-Path $portablePython "python.exe"
    Write-Host "[5/8] Installing dependencies into the portable runtime..."
    Invoke-Checked -FilePath $embeddedPython -Arguments @($getPipPath, "--disable-pip-version-check", "--no-warn-script-location")
    Invoke-Checked -FilePath $embeddedPython -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location", "--no-compile", "--upgrade", "-r", $requirementsPath)

    Get-ChildItem -LiteralPath $packageRoot -Directory -Filter "__pycache__" -Recurse -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force

    Write-Host "[6/8] Writing the portable launcher..."
    $launcher = @'
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_HOST = "127.0.0.1"
APP_PORT = 8765
APP_URL = f"http://{APP_HOST}:{APP_PORT}"


def configure_runtime() -> None:
    root = Path(__file__).resolve().parent
    data_dir = root / "data"
    projects_dir = data_dir / "projects"
    data_dir.mkdir(parents=True, exist_ok=True)
    projects_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root / "backend"))
    os.chdir(root)
    os.environ["DATABASE_URL"] = f"sqlite:///{(data_dir / 'community_prediction.db').as_posix()}"
    os.environ["PROJECTS_ROOT"] = str(projects_dir)
    os.environ.setdefault("COMMUNITY_BUILD_ID", "portable-v__APP_VERSION__")


def port_is_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((APP_HOST, APP_PORT))
        except OSError:
            return False
    return True


def open_browser_when_ready() -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"{APP_URL}/api/health", timeout=1) as response:
                if response.status == 200:
                    if os.environ.get("COMMUNITY_NO_BROWSER") != "1":
                        webbrowser.open(APP_URL)
                    return
        except Exception:
            time.sleep(0.25)


def main() -> int:
    configure_runtime()
    if not port_is_available():
        print(f"Startup failed: port {APP_PORT} is already in use. Close the previous launcher window and retry.")
        return 2
    print("Community Prediction System is starting...")
    print(f"Application URL: {APP_URL}")
    print("Keep this window open while using the system. Close it to stop the service.")
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    try:
        import uvicorn
        uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=False, access_log=False, log_level="warning")
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Startup failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@
    $launcher = $launcher.Replace("__APP_VERSION__", $appVersion)
    Set-Content -LiteralPath (Join-Path $packageRoot "launcher.py") -Value $launcher -Encoding UTF8

    $batchLauncher = @'
@echo off
setlocal
cd /d "%~dp0"
title Community Prediction System
"%~dp0runtime\python\python.exe" "%~dp0launcher.py"
if errorlevel 1 (
    echo.
    echo Startup failed. Please check the message above.
    pause
)
endlocal
'@
    Set-Content -LiteralPath (Join-Path $packageRoot "Start-System.bat") -Value $batchLauncher -Encoding ASCII

    Write-Host "[7/8] Verifying the portable runtime..."
    $backendImportPath = (Join-Path $packageRoot "backend").Replace("'", "''")
    $importCheck = "import fastapi, uvicorn, sqlalchemy, openpyxl, docx, PIL; import sys; sys.path.insert(0, r'$backendImportPath'); import app.main; print('portable-runtime-ok')"
    Invoke-Checked -FilePath $embeddedPython -Arguments @("-c", $importCheck)

    Write-Host "[8/8] Creating the ZIP archive and checksum..."
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
    $hash = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
    "$($hash.Hash)  $([System.IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $hashPath -Encoding ASCII

    $zipItem = Get-Item -LiteralPath $zipPath
    Write-Host ""
    Write-Host "Portable package created successfully." -ForegroundColor Green
    Write-Host "Folder: $packageRoot"
    Write-Host "ZIP:    $zipPath"
    Write-Host "Size:   $([math]::Round($zipItem.Length / 1MB, 2)) MB"
    Write-Host "SHA256: $($hash.Hash)"
}
catch {
    Write-Host ""
    Write-Host "Portable build failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
