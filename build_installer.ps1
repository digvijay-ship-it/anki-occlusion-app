param(
    [switch]$SkipTests,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $root "dist"
$buildDir = Join-Path $root "build"
$releaseDir = Join-Path $root "release"
$installerDir = Join-Path $root "installer"
$generatedDir = Join-Path $installerDir "_generated"
$zipStageDir = Join-Path $generatedDir "zip_payload"
$zipPath = Join-Path $releaseDir "AnkiOcclusion.zip"
$setupPath = Join-Path $releaseDir "AnkiOcclusionSetup.exe"
$appBundleDir = Join-Path $distDir "AnkiOcclusion"
$appExePath = Join-Path $appBundleDir "AnkiOcclusion.exe"

Set-Location $root

Write-Host "[DEBUG][installer] root=$root"

$cscPath = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $cscPath)) {
    throw "C# compiler was not found at $cscPath"
}

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
New-Item -ItemType Directory -Force -Path $generatedDir | Out-Null

if (-not $SkipTests) {
    Write-Host "[DEBUG][installer] tests_start"
    python -m unittest tests.test_packaging tests.test_storage_paths tests.test_theme_manager tests.test_home_screen -q
    if ($LASTEXITCODE -ne 0) {
        throw "Installer preflight tests failed."
    }
    Write-Host "[DEBUG][installer] tests_ok"
}

if (-not $SkipBuild) {
    foreach ($path in @($buildDir, $distDir)) {
        if (Test-Path -LiteralPath $path) {
            Write-Host "[DEBUG][installer] removing=$path"
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }

    Write-Host "[DEBUG][installer] pyinstaller_start"
    pyinstaller --noconfirm AnkiOcclusion.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
} else {
    Write-Host "[DEBUG][installer] skip_build_using_existing_dist"
}

if (-not (Test-Path -LiteralPath $appExePath)) {
    throw "Built app executable not found at $appExePath"
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
if (Test-Path -LiteralPath $setupPath) {
    Remove-Item -LiteralPath $setupPath -Force
}


if (Test-Path -LiteralPath $zipStageDir) {
    Remove-Item -LiteralPath $zipStageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $zipStageDir | Out-Null

$staged = $false
for ($attempt = 1; $attempt -le 5; $attempt++) {
    try {
        Write-Host "[DEBUG][installer] stage_attempt=$attempt source=$appBundleDir"
        Copy-Item -Path (Join-Path $appBundleDir "*") -Destination $zipStageDir -Recurse -Force
        $staged = $true
        break
    } catch {
        if ($attempt -eq 5) {
            throw
        }
        Write-Host "[DEBUG][installer] stage_retry attempt=$attempt"
        Start-Sleep -Seconds 2
    }
}

if (-not $staged) {
    throw "Could not stage the built app for zipping."
}

Write-Host "[DEBUG][installer] zip_start source=$zipStageDir"
$zipped = $false
for ($attempt = 1; $attempt -le 5; $attempt++) {
    try {
        Write-Host "[DEBUG][installer] zip_attempt=$attempt"
        Compress-Archive -Path (Join-Path $zipStageDir "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force
        $zipped = $true
        break
    } catch {
        if ($attempt -eq 5) {
            throw
        }
        Write-Host "[DEBUG][installer] zip_retry attempt=$attempt"
        Start-Sleep -Seconds 3
    }
}

if (-not $zipped) {
    throw "Could not create installer payload zip."
}

$cscPath = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $cscPath)) {
    throw "C# compiler was not found at $cscPath"
}

Write-Host "[DEBUG][installer] compiling setup executable target=$setupPath"
$cscProc = Start-Process -FilePath $cscPath -ArgumentList @(
    "/target:winexe",
    "/out:release\AnkiOcclusionSetup.exe",
    "/resource:release\AnkiOcclusion.zip,AnkiOcclusion.zip",
    "/resource:installer\install.ps1,install.ps1",
    "installer\installer.cs"
) -PassThru -Wait

if ($cscProc.ExitCode -ne 0) {
    throw "C# compilation failed."
}

Write-Host "[DEBUG][installer] setup_ready path=$setupPath"
