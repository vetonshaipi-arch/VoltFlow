# Build VoltFlow Windows executable (PyInstaller onedir)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    Write-Error "Virtual env not found. Run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
}

& $Py -m pip install -q pyinstaller
Write-Host "Building VoltFlow.exe ..."
& $Py -m PyInstaller voltflow.spec --noconfirm
if ($LASTEXITCODE -ge 1) { exit $LASTEXITCODE }

$Out = Join-Path $Root 'dist\VoltFlow\VoltFlow.exe'
if (Test-Path $Out) {
    Write-Host ""
    Write-Host "Done: $Out"
    Write-Host "Copy the whole dist\VoltFlow folder to deploy (includes Qt DLLs and resources)."
} else {
    Write-Error "Build finished but VoltFlow.exe was not found."
}
