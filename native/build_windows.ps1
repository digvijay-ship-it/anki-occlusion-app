param(
    [string]$Configuration = "Release",
    [string]$Architecture = "x64",
    [switch]$SkipMupdfBuild
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$buildDir = Join-Path $scriptDir "build"

Write-Host "== Native PDF backend build ==" -ForegroundColor Cyan
Write-Host "Repo root : $repoRoot"
Write-Host "Build dir : $buildDir"
Write-Host "Config    : $Configuration"
Write-Host "Arch      : $Architecture"

function Resolve-ToolPath {
    param(
        [string]$CommandName,
        [string[]]$Fallbacks
    )
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    foreach ($candidate in $Fallbacks) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    return $null
}

$cmake = Resolve-ToolPath "cmake" @(
    "C:\Program Files\CMake\bin\cmake.exe",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
)
if (-not $cmake) {
    throw "cmake not found. Install CMake or Visual Studio CMake tools first."
}

$msbuild = Resolve-ToolPath "MSBuild" @(
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\amd64\MSBuild.exe"
)

$mupdfRoot = Join-Path $scriptDir "mupdf-src"
$mupdfSolution = Join-Path $mupdfRoot "platform\win32\mupdf.sln"
$mupdfLibDir = Join-Path $mupdfRoot "platform\win32\$Architecture\$Configuration"
$mupdfLib = Join-Path $mupdfLibDir "libmupdf.lib"

if (-not $SkipMupdfBuild) {
    if (-not (Test-Path $mupdfSolution)) {
        throw "MuPDF source tree missing at $mupdfRoot"
    }
    if (-not $msbuild) {
        throw "MSBuild not found. Install Visual Studio Build Tools first."
    }
    if (-not (Test-Path $mupdfLib)) {
        Write-Host "Building MuPDF static libraries..." -ForegroundColor Yellow
        & $msbuild $mupdfSolution /m /t:libmupdf /p:Configuration=$Configuration /p:Platform=$Architecture /p:PlatformToolset=v143
        if ($LASTEXITCODE -ne 0) {
            throw "MuPDF build failed with exit code $LASTEXITCODE"
        }
    }
}

if (-not (Test-Path $mupdfLib)) {
    throw "Missing MuPDF library: $mupdfLib"
}

& $cmake -S $scriptDir -B $buildDir -A $Architecture
if ($LASTEXITCODE -ne 0) {
    throw "CMake configure failed with exit code $LASTEXITCODE"
}

& $cmake --build $buildDir --config $Configuration
if ($LASTEXITCODE -ne 0) {
    throw "CMake build failed with exit code $LASTEXITCODE"
}

$dllPath = Join-Path $buildDir $Configuration
$dllFile = Join-Path $dllPath "anki_pdf_native.dll"
if (Test-Path $dllFile) {
    Write-Host "Built: $dllFile" -ForegroundColor Green
} else {
    Write-Warning "Build finished but DLL not found at expected path: $dllFile"
}
