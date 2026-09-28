$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$testRoot = Join-Path $workspaceRoot ("runtime\package-single-exe\" + $stamp)
$isolatedExe = Join-Path $testRoot "CommunityPredictionSystem.exe"
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $workspaceRoot "release\CommunityPredictionSystem.exe") -Destination $isolatedExe

function Stop-IsolatedApplication {
    param([string]$ExecutablePath)
    Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $ExecutablePath } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# Verify that the exe works after being copied by itself, without _internal or other files.
$env:COMMUNITY_DATA_ROOT = Join-Path $testRoot "data"
$env:COMMUNITY_NO_BROWSER = "1"
$env:COMMUNITY_PORT = "18990"
$app = Start-Process -FilePath $isolatedExe -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru
try {
    $ready = $false
    foreach ($attempt in 1..40) {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:18990/api/health" -TimeoutSec 1
            $ready = $health.status -eq "ok"
            if ($ready) { break }
        }
        catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $ready) { throw "The isolated single-file executable did not become ready." }
    if (-not $health.buildId) { throw "Packaged health response did not expose a build id." }
    $index = Invoke-WebRequest "http://127.0.0.1:18990/?build=$($health.buildId)" -UseBasicParsing
    if ($index.Headers["Cache-Control"] -notlike "*no-store*") { throw "The HTML shell may still be served from stale browser cache." }
    if ($index.Content -match 'type="module"') { throw "The desktop package still depends on ES-module execution." }
    if ($index.Content -notmatch '<script defer src=') { throw "The desktop package does not reference a classic deferred script." }
    $assetMatch = [regex]::Match($index.Content, 'src="\.?/?(assets/[^\"]+\.js)"')
    if (-not $assetMatch.Success) { throw "The packaged HTML did not reference its JavaScript bundle." }
    if ($assetMatch.Groups[1].Value -notmatch 'community-prediction-standalone\.[0-9a-f]{12}\.js$') { throw "The packaged JavaScript filename is not content-versioned; another release may remain cached." }
    $asset = Invoke-WebRequest ("http://127.0.0.1:18990/" + $assetMatch.Groups[1].Value) -UseBasicParsing
    if ($asset.StatusCode -ne 200 -or $asset.RawContentLength -lt 1000) { throw "The packaged JavaScript bundle is unavailable." }
    if ($asset.Content -match 'process\.env') { throw "The packaged JavaScript still contains a Node-only process.env reference." }
    $browserCandidates = @(@(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ })
    $browserRendered = $null
    if ($browserCandidates.Count -gt 0) {
        $browserProfile = Join-Path $testRoot "browser-profile"
        $dom = & $browserCandidates[0] --headless=new --disable-gpu --no-first-run --disable-extensions --virtual-time-budget=10000 --user-data-dir=$browserProfile --dump-dom "http://127.0.0.1:18990/?e2e=classic" 2>$null
        if ($dom -match "界面资源未能加载") { throw "The browser displayed the startup watchdog instead of the application." }
        if ($dom -notmatch 'aria-label="完整社区预测功能"') { throw "The browser did not render the React workspace navigation." }
        $browserRendered = $true
    }
    $log = Get-ChildItem (Join-Path $testRoot "data\logs") -File | Select-Object -First 1
    [pscustomobject]@{ SingleExe = $ready; BuildId = $health.buildId; HtmlNoCache = $true; JavaScriptLoaded = $true; BrowserRendered = $browserRendered; LogExists = [bool]$log; Size = (Get-Item $isolatedExe).Length } | ConvertTo-Json
}
finally {
    if (-not $app.HasExited) { Stop-Process -Id $app.Id -Force }
    Stop-IsolatedApplication -ExecutablePath $isolatedExe
}

# Occupy the requested port with an unrelated service and confirm automatic fallback.
$env:COMMUNITY_DATA_ROOT = Join-Path $testRoot "port-fallback-data"
$env:COMMUNITY_PORT = "18991"
$python = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
$dummy = Start-Process -FilePath $python -ArgumentList "-m", "http.server", "18991", "--bind", "127.0.0.1" -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 600
$fallback = Start-Process -FilePath $isolatedExe -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru
try {
    $ready = $false
    foreach ($attempt in 1..40) {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:18992/api/health" -TimeoutSec 1
            $ready = $health.status -eq "ok"
            if ($ready) { break }
        }
        catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $ready) { throw "Automatic port fallback did not become ready." }
    [pscustomobject]@{ OccupiedPort = 18991; SelectedPort = 18992; Ready = $ready } | ConvertTo-Json
}
finally {
    if (-not $fallback.HasExited) { Stop-Process -Id $fallback.Id -Force }
    Stop-IsolatedApplication -ExecutablePath $isolatedExe
    if (-not $dummy.HasExited) { Stop-Process -Id $dummy.Id -Force }
}
