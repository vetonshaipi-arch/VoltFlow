# Package VoltFlow release: exe + zipped source in release/VoltFlow-<version>/
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$versionFile = Join-Path $Root 'version.py'
if (-not (Test-Path $versionFile)) { throw 'version.py not found' }
$ver = ([regex]::Match((Get-Content $versionFile -Raw), "APP_VERSION\s*=\s*['""]([^'""]+)['""]")).Groups[1].Value
if (-not $ver) { throw 'Could not read APP_VERSION from version.py' }

$exeIn = Join-Path $Root 'dist\VoltFlow.exe'
if (-not (Test-Path $exeIn)) {
    Write-Host 'VoltFlow.exe not found — building first ...'
    & (Join-Path $Root 'build_voltflow.bat')
    if (-not (Test-Path $exeIn)) { throw "Build failed: $exeIn missing" }
}

$releaseName = "VoltFlow-$ver"
$releaseDir = Join-Path $Root "release\$releaseName"
$sourceZip = Join-Path $releaseDir "$releaseName-source.zip"
$readme = Join-Path $releaseDir 'README.txt'

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
Copy-Item -Force $exeIn (Join-Path $releaseDir 'VoltFlow.exe')

$excludeDirs = @(
    '.venv', 'build', 'dist', 'release', '__pycache__', '.git',
    '.cursor', 'agent-transcripts', 'node_modules'
)
$excludeNames = @('*.pyc', '*.pyo', '*.exe', '*.zip')

$staging = Join-Path $env:TEMP "voltflow-src-$ver"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Get-ChildItem -Path $Root -Force | ForEach-Object {
    if ($excludeDirs -contains $_.Name) { return }
    if ($_.PSIsContainer) {
        Copy-Item -Recurse -Force $_.FullName (Join-Path $staging $_.Name)
    } else {
        Copy-Item -Force $_.FullName (Join-Path $staging $_.Name)
    }
}

Get-ChildItem -Path $staging -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $staging -Recurse -Include '*.pyc','*.pyo' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

if (Test-Path $sourceZip) { Remove-Item -Force $sourceZip }
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $sourceZip -CompressionLevel Optimal
Remove-Item -Recurse -Force $staging

@"
VoltFlow $ver — Windows release
================================

VoltFlow.exe
  Single-file application for Windows 10/11 (64-bit).
  Double-click to run. No Python install required.
  First launch may take a few seconds while files unpack.

$releaseName-source.zip
  Project source (Python). Excludes .venv, build/, and dist/.
  To run from source:
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt PyInstaller
    python switchboard.py

  To rebuild the exe:
    build_voltflow.bat

KSA · 60 Hz LV distribution design.
"@ | Set-Content -Path $readme -Encoding UTF8

Write-Host ""
Write-Host "Release folder: $releaseDir"
Write-Host "  VoltFlow.exe"
Write-Host "  $([System.IO.Path]::GetFileName($sourceZip))"
Write-Host "  README.txt"
