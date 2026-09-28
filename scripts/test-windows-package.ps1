$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$smokeRoot = Join-Path $workspaceRoot ("runtime\package-smoke\" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$exe = (Resolve-Path (Join-Path $workspaceRoot "release\CommunityPredictionSystem.exe")).Path
New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null

$env:COMMUNITY_DATA_ROOT = $smokeRoot
$env:COMMUNITY_NO_BROWSER = "1"
$env:COMMUNITY_PORT = "18876"
$process = Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden -PassThru
try {
    $ready = $false
    foreach ($attempt in 1..30) {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:18876/api/health" -TimeoutSec 2
            $ready = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) { throw "Packaged application did not become ready." }
    $projects = @(Invoke-RestMethod "http://127.0.0.1:18876/api/projects")
    $quality = Invoke-RestMethod ("http://127.0.0.1:18876/api/projects/{0}/quality?kind=population" -f $projects[0].id)
    $projectBody = @{ name = ("打包版调研表导入验证_" + (Get-Date -Format "HHmmss")) } | ConvertTo-Json
    $testProject = Invoke-RestMethod "http://127.0.0.1:18876/api/projects" -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($projectBody))
    # Avoid a non-ASCII literal here because Windows PowerShell 5 may read a
    # UTF-8 script without BOM using the local ANSI code page.
    $surveyFile = (Get-ChildItem -LiteralPath $workspaceRoot -Filter "*.xlsx" -File -Recurse | Where-Object { $_.Length -eq 7546123 } | Select-Object -First 1).FullName
    if (-not $surveyFile) { throw "Survey workbook was not found." }
    Add-Type -AssemblyName System.Net.Http
    $httpClient = New-Object System.Net.Http.HttpClient
    $multipart = New-Object System.Net.Http.MultipartFormDataContent
    $fileStream = [IO.File]::Open($surveyFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    $fileContent = New-Object System.Net.Http.StreamContent($fileStream)
    $fileContent.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    $multipart.Add($fileContent, "file", "survey.xlsx")
    try {
        $importResponse = $httpClient.PostAsync(("http://127.0.0.1:18876/api/projects/{0}/communities/import" -f $testProject.id), $multipart).GetAwaiter().GetResult()
        if (-not $importResponse.IsSuccessStatusCode) { throw ("Packaged survey import request failed: " + $importResponse.StatusCode) }
        $importJson = $importResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    }
    finally {
        $fileStream.Dispose()
        $multipart.Dispose()
        $httpClient.Dispose()
    }
    $import = $importJson | ConvertFrom-Json
    $importedPopulation = ($import.community.age_counts.PSObject.Properties.Value | Measure-Object -Sum).Sum
    if ($import.success_count -ne 1 -or $import.community.code -ne "120104-A" -or $importedPopulation -ne 8516) { throw "Packaged application did not convert the aggregate survey workbook." }
    $page = Invoke-WebRequest "http://127.0.0.1:18876/" -UseBasicParsing
    [pscustomobject]@{
        Health = $health.status
        ProjectCount = $projects.Count
        Demo = $projects[0].name
        QualityReady = $quality.ready
        ImportedCommunity = $import.community.name
        ImportedPopulation = $importedPopulation
        PageStatus = $page.StatusCode
        DataRoot = $smokeRoot
    } | ConvertTo-Json
}
finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    $listener = Get-NetTCPConnection -State Listen -LocalPort 18876 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue }
}
