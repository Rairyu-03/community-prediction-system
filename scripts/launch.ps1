$ErrorActionPreference = "Stop"
$launcherJobHandle = [IntPtr]::Zero

if (-not ("CommunityLauncher.NativeJob" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace CommunityLauncher {
    public static class NativeJob {
        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);

        [DllImport("kernel32.dll")]
        private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);

        [DllImport("kernel32.dll")]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll")]
        public static extern bool CloseHandle(IntPtr handle);

        public static IntPtr CreateKillOnCloseJob() {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = 0x00002000;
            int length = Marshal.SizeOf(info);
            IntPtr pointer = Marshal.AllocHGlobal(length);
            try {
                Marshal.StructureToPtr(info, pointer, false);
                if (!SetInformationJobObject(job, 9, pointer, (uint)length))
                    throw new System.ComponentModel.Win32Exception();
            }
            finally { Marshal.FreeHGlobal(pointer); }
            return job;
        }

        public static bool TryAddProcess(IntPtr job, int processId) {
            using (Process process = Process.GetProcessById(processId)) {
                return AssignProcessToJobObject(job, process.Handle);
            }
        }
    }
}
"@
}

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
    & $startScript -NoReload

    $launcherJobHandle = [CommunityLauncher.NativeJob]::CreateKillOnCloseJob()
    $processIds = Get-Content -LiteralPath (Join-Path $workspaceRoot "runtime\dev-pids.json") -Raw | ConvertFrom-Json
    $managedProcessIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($processId in @($processIds.backend, $processIds.frontend)) {
        [void]$managedProcessIds.Add([int]$processId)
    }
    $allProcesses = @(Get-CimInstance Win32_Process)
    $addedChild = $true
    while ($addedChild) {
        $addedChild = $false
        foreach ($process in $allProcesses) {
            if ($managedProcessIds.Contains([int]$process.ParentProcessId) -and -not $managedProcessIds.Contains([int]$process.ProcessId)) {
                [void]$managedProcessIds.Add([int]$process.ProcessId)
                $addedChild = $true
            }
        }
    }
    foreach ($processId in $managedProcessIds) {
        # A process can already belong to a host-managed job (for example in a
        # CI runner). In an ordinary desktop launch this succeeds and closing
        # the window terminates the complete process tree; otherwise the
        # finally block below still performs the same cleanup.
        try {
            [void][CommunityLauncher.NativeJob]::TryAddProcess($launcherJobHandle, [int]$processId)
        }
        catch [System.ArgumentException] {
            # A short-lived package-manager or bootstrap child may exit between
            # discovery and assignment; it does not host either web service.
        }
    }

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

    # The Windows Python launcher can hand the listening socket to a spawned
    # interpreter. Add the actual port owners after readiness so closing this
    # launcher window also closes those service processes.
    foreach ($servicePort in @(5173, 8000)) {
        foreach ($listener in @(Get-NetTCPConnection -LocalPort $servicePort -State Listen -ErrorAction SilentlyContinue)) {
            try {
                [void][CommunityLauncher.NativeJob]::TryAddProcess($launcherJobHandle, [int]$listener.OwningProcess)
            }
            catch [System.ArgumentException] {
            }
        }
    }

    if ($env:COMMUNITY_NO_BROWSER -ne "1") {
        Start-Process "http://127.0.0.1:5173"
    }

    Write-Host ""
    Write-Host "Started successfully." -ForegroundColor Green
    Write-Host "  Application: http://127.0.0.1:5173"
    Write-Host "  API docs:    http://127.0.0.1:8000/docs"
    Write-Host ""
    Write-Host "Keep this window open while using the system." -ForegroundColor Cyan
    Write-Host "Close this window to stop all services." -ForegroundColor Cyan

    while ($true) {
        Start-Sleep -Seconds 1
    }
}
catch {
    if ($stopScript -and (Test-Path -LiteralPath (Join-Path $workspaceRoot "runtime\dev-pids.json"))) {
        & $stopScript
    }
    Write-Host ""
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if ($stopScript -and $workspaceRoot -and (Test-Path -LiteralPath (Join-Path $workspaceRoot "runtime\dev-pids.json"))) {
        & $stopScript 2>$null
    }
    if ($launcherJobHandle -ne [IntPtr]::Zero) {
        [CommunityLauncher.NativeJob]::CloseHandle($launcherJobHandle) | Out-Null
    }
}
