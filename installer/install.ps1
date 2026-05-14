param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$zipPath = Join-Path $scriptDir "AnkiOcclusion.zip"
$installDir = Join-Path $env:LOCALAPPDATA "Programs\AnkiOcclusion"
$exePath = Join-Path $installDir "AnkiOcclusion.exe"

if (-not (Test-Path -LiteralPath $zipPath)) {
    throw "Installer payload not found: $zipPath"
}

if (Test-Path -LiteralPath $installDir) {
    Remove-Item -LiteralPath $installDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $installDir -Force

if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Installed executable not found: $exePath"
}

$shell = New-Object -ComObject WScript.Shell
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Anki Occlusion.lnk"
$startMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "Anki Occlusion"
$startMenuShortcut = Join-Path $startMenuDir "Anki Occlusion.lnk"

New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null

foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = $installDir
    $shortcut.IconLocation = $exePath
    $shortcut.Save()
}

if (-not $Quiet) {
    Write-Host "Anki Occlusion installed to $installDir"
}
