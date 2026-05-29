param(
    [switch]$AlsoStopKnownPorts
)

$ErrorActionPreference = "Stop"

$WebRoot = $PSScriptRoot
$RunDir = Join-Path $WebRoot ".run"
$PidFiles = @(
    Join-Path $RunDir "frontend.pid"
    Join-Path $RunDir "backend.pid"
)

function Stop-PidFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $pidText = (Get-Content -LiteralPath $Path -Raw).Trim()
    if (-not $pidText) {
        Remove-Item -LiteralPath $Path -Force
        return
    }

    $processId = [int]$pidText
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId -Force
        Write-Host "Stopped PID $processId"
    }
    Remove-Item -LiteralPath $Path -Force
}

foreach ($pidFile in $PidFiles) {
    Stop-PidFile -Path $pidFile
}

if ($AlsoStopKnownPorts) {
    foreach ($port in @(8000, 5173)) {
        $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($listener in $listeners) {
            if ($listener.OwningProcess) {
                Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
                Write-Host "Stopped process on port $port (PID $($listener.OwningProcess))"
            }
        }
    }
}

Write-Host "Web app stop command finished."
