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
$iexpressPath = Join-Path $env:WINDIR "System32\iexpress.exe"
$appBundleDir = Join-Path $distDir "AnkiOcclusion"
$appExePath = Join-Path $appBundleDir "AnkiOcclusion.exe"
$tempRoot = Join-Path $env:TEMP "AnkiOcclusionInstaller"
$sedInstallerDir = Join-Path $tempRoot "installer"
$sedPayloadDir = Join-Path $tempRoot "payload"
$tempSetupPath = Join-Path $tempRoot "AnkiOcclusionSetup.exe"
$sedPath = Join-Path $tempRoot "AnkiOcclusionInstaller.sed"

Set-Location $root

Write-Host "[DEBUG][installer] root=$root"

if (-not (Test-Path -LiteralPath $iexpressPath)) {
    throw "IExpress was not found at $iexpressPath"
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
if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $sedInstallerDir | Out-Null
New-Item -ItemType Directory -Force -Path $sedPayloadDir | Out-Null

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

Copy-Item -LiteralPath (Join-Path $installerDir "install.cmd") -Destination $sedInstallerDir -Force
Copy-Item -LiteralPath (Join-Path $installerDir "install.ps1") -Destination $sedInstallerDir -Force
Copy-Item -LiteralPath $zipPath -Destination (Join-Path $sedPayloadDir "AnkiOcclusion.zip") -Force

$sedContent = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=1
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=Anki Occlusion has been installed.
TargetName=$tempSetupPath
FriendlyName=Anki Occlusion Setup
AppLaunched=cmd.exe /c install.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=cmd.exe /c install.cmd /quiet
SourceFiles=SourceFiles
[Strings]
FILE0="install.cmd"
FILE1="install.ps1"
FILE2="AnkiOcclusion.zip"
[SourceFiles]
SourceFiles0=$sedInstallerDir
SourceFiles1=$sedPayloadDir
[SourceFiles0]
%FILE0%=
%FILE1%=
[SourceFiles1]
%FILE2%=
"@

Set-Content -Path $sedPath -Value $sedContent -Encoding ASCII

Write-Host "[DEBUG][installer] iexpress_start target=$setupPath"
$iexpressProc = Start-Process -FilePath $iexpressPath -ArgumentList @("/N", $sedPath) -PassThru -Wait
if ($iexpressProc.ExitCode -ne 0) {
    throw "IExpress failed to create the installer."
}

if (-not (Test-Path -LiteralPath $tempSetupPath)) {
    throw "Installer executable was not created at $tempSetupPath"
}

Copy-Item -LiteralPath $tempSetupPath -Destination $setupPath -Force
Write-Host "[DEBUG][installer] setup_ready path=$setupPath"
