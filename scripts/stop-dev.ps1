$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidFile = Join-Path $workspaceRoot "runtime\dev-pids.json"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "No development service PID file was found."
    exit 0
}

$processIds = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
$treeIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($processId in @($processIds.backend, $processIds.frontend)) {
    if ($processId) {
        [void]$treeIds.Add([int]$processId)
    }
}

# Capture descendants before stopping their parents. Uvicorn's reload worker is
# a spawned Python process whose command line does not necessarily contain the
# workspace path, so command-line matching alone can leave port 8000 occupied.
$allProcesses = @(Get-CimInstance Win32_Process)
$addedChild = $true
while ($addedChild) {
    $addedChild = $false
    foreach ($process in $allProcesses) {
        if ($treeIds.Contains([int]$process.ParentProcessId) -and -not $treeIds.Contains([int]$process.ProcessId)) {
            [void]$treeIds.Add([int]$process.ProcessId)
            $addedChild = $true
        }
    }
}

$depthById = @{}
foreach ($processId in $treeIds) { $depthById[$processId] = 0 }
for ($pass = 0; $pass -lt $treeIds.Count; $pass++) {
    foreach ($process in $allProcesses) {
        if ($treeIds.Contains([int]$process.ProcessId) -and $treeIds.Contains([int]$process.ParentProcessId)) {
            $candidateDepth = $depthById[[int]$process.ParentProcessId] + 1
            if ($candidateDepth -gt $depthById[[int]$process.ProcessId]) {
                $depthById[[int]$process.ProcessId] = $candidateDepth
            }
        }
    }
}

# Stop parents first so a reload/supervisor process cannot replace a worker
# between the two termination calls, then stop the captured descendants.
foreach ($processId in @($treeIds | Sort-Object { $depthById[$_] })) {
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
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

# On Windows, Python's launcher may transfer the listening socket to a spawned
# interpreter whose command line no longer includes the workspace path. The PID
# file proves these ports belong to this launch, so clean up their owners too.
foreach ($servicePort in @(5173, 8000)) {
    foreach ($listener in @(Get-NetTCPConnection -LocalPort $servicePort -State Listen -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item -LiteralPath $pidFile -Force
Write-Host "Development services stopped."
