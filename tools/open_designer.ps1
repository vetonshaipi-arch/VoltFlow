# Open Qt Designer on VoltFlow UI forms
$root = Split-Path -Parent $PSScriptRoot
$designer = Join-Path $root ".venv\Scripts\pyside6-designer.exe"
$forms = Join-Path $root "ui\forms"
if (-not (Test-Path $designer)) {
    Write-Error "pyside6-designer not found. Run: pip install pyside6"
    exit 1
}
$form = $args[0]
if ($form) {
    if (-not $form.EndsWith('.ui')) { $form += '.ui' }
    Start-Process $designer (Join-Path $forms $form)
} else {
    Start-Process $designer $forms
}
