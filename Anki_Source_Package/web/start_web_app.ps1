param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$WebRoot = $PSScriptRoot
$BackendDir = Join-Path $WebRoot "backend"
$FrontendDir = Join-Path $WebRoot "frontend"
$RunDir = Join-Path $WebRoot ".run"
$BackendLog = Join-Path $RunDir "backend.log"
$BackendErr = Join-Path $RunDir "backend.err.log"
$FrontendLog = Join-Path $RunDir "frontend.log"
$FrontendErr = Join-Path $RunDir "frontend.err.log"
$BackendPidFile = Join-Path $RunDir "backend.pid"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Test-CommandAvailable {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Port {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

if (-not (Test-CommandAvailable -Name "python")) {
    throw "python was not found on PATH."
}

if (-not (Test-CommandAvailable -Name "npm")) {
    throw "npm was not found on PATH."
}

if (-not (Test-PortListening -Port $BackendPort)) {
    $backend = Start-Process `
        -FilePath "python" `
        -ArgumentList @("-m", "uvicorn", "run:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $BackendLog `
        -RedirectStandardError $BackendErr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $BackendPidFile -Value $backend.Id
    Write-Host "Started backend on http://127.0.0.1:$BackendPort (PID $($backend.Id))"
} else {
    Write-Host "Backend already listening on http://127.0.0.1:$BackendPort"
}

if (-not (Test-PortListening -Port $FrontendPort)) {
    $frontendCommand = "set VITE_API_BASE=http://127.0.0.1:$BackendPort&& npm run dev -- --host 127.0.0.1 --port $FrontendPort"
    $frontend = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList @("/c", $frontendCommand) `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput $FrontendLog `
        -RedirectStandardError $FrontendErr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $FrontendPidFile -Value $frontend.Id
    Write-Host "Started frontend on http://127.0.0.1:$FrontendPort (PID $($frontend.Id))"
} else {
    Write-Host "Frontend already listening on http://127.0.0.1:$FrontendPort"
}

$backendReady = Wait-Port -Port $BackendPort
$frontendReady = Wait-Port -Port $FrontendPort

if (-not $backendReady) {
    Write-Warning "Backend did not become ready. Check $BackendErr"
}

if (-not $frontendReady) {
    Write-Warning "Frontend did not become ready. Check $FrontendErr"
}

if ($backendReady -and $frontendReady -and -not $NoBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort"
}

Write-Host ""
Write-Host "Web app:  http://127.0.0.1:$FrontendPort"
Write-Host "API:      http://127.0.0.1:$BackendPort"
Write-Host "Logs:     $RunDir"
Write-Host "Stop it:  web\stop_web_app.cmd"
