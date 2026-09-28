$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
$frontendRoot = Join-Path $workspaceRoot "frontend"
$releaseRoot = Join-Path $workspaceRoot "release"
$applicationRoot = Join-Path $releaseRoot "CommunityPredictionSystem"
$packageStageRoot = Join-Path $workspaceRoot "build\package-stage"
$stagedApplicationRoot = Join-Path $packageStageRoot "CommunityPredictionSystem"
$builtExe = Join-Path $releaseRoot "CommunityPredictionSystem.exe"
$zipPath = Join-Path $releaseRoot "CommunityPredictionSystem-Windows-x64.zip"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment was not found. Run the development launcher first."
}
$pnpm = Get-Command pnpm.cmd -ErrorAction Stop

Write-Host "[1/4] Building frontend..."
Push-Location $frontendRoot
try {
    & $pnpm.Source install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
    & $pnpm.Source run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}
finally {
    Pop-Location
}
$frontendIndex = Join-Path $frontendRoot "dist\index.html"
$buildId = (Get-FileHash -Algorithm SHA256 -LiteralPath $frontendIndex).Hash.Substring(0, 12).ToLowerInvariant()
$versionedZipPath = Join-Path $releaseRoot ("CommunityPredictionSystem-Windows-x64-" + $buildId + ".zip")

Write-Host "[2/4] Installing packaging tools..."
& $pythonPath -m pip install -r (Join-Path $workspaceRoot "backend\requirements.txt") -r (Join-Path $workspaceRoot "packaging\requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "Python packaging dependency installation failed." }

Write-Host "[3/4] Building portable application..."
& $pythonPath -m PyInstaller --noconfirm --clean --distpath $releaseRoot --workpath (Join-Path $workspaceRoot "build\pyinstaller") (Join-Path $workspaceRoot "packaging\community_prediction.spec")
if ($LASTEXITCODE -ne 0) { throw "Windows application build failed." }
if (-not (Test-Path -LiteralPath $builtExe)) { throw "Portable executable was not generated." }
if (Test-Path -LiteralPath $packageStageRoot) {
    $resolvedBuild = (Resolve-Path -LiteralPath (Join-Path $workspaceRoot "build")).Path
    $resolvedStage = (Resolve-Path -LiteralPath $packageStageRoot).Path
    if (-not $resolvedStage.StartsWith($resolvedBuild + [IO.Path]::DirectorySeparatorChar)) { throw "Unsafe package staging cleanup target." }
    Remove-Item -LiteralPath $packageStageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stagedApplicationRoot -Force | Out-Null
Copy-Item -LiteralPath $builtExe -Destination (Join-Path $stagedApplicationRoot "CommunityPredictionSystem.exe") -Force
Copy-Item -LiteralPath (Join-Path $workspaceRoot "packaging\WINDOWS_README.txt") -Destination $stagedApplicationRoot -Force
Copy-Item -LiteralPath (Join-Path $workspaceRoot "packaging\SINGLE_WORKSPACE_GUIDE.md") -Destination $stagedApplicationRoot -Force

Write-Host "[4/4] Creating release archive..."
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -LiteralPath $stagedApplicationRoot -DestinationPath $zipPath -CompressionLevel Optimal
Copy-Item -LiteralPath $zipPath -Destination $versionedZipPath -Force
Set-Content -LiteralPath (Join-Path $releaseRoot "LATEST_BUILD.txt") -Encoding UTF8 -Value @(
    "Build ID: $buildId"
    "Versioned package: $([IO.Path]::GetFileName($versionedZipPath))"
    "SHA256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $versionedZipPath).Hash)"
)
Write-Host "Build completed: $versionedZipPath" -ForegroundColor Green
