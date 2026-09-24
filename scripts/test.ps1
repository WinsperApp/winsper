$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

& .\.venv\Scripts\python.exe -m ruff check voicepilot tests scripts
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

$env:QT_QPA_PLATFORM = "offscreen"
& .\.venv\Scripts\python.exe -m pytest
exit $LASTEXITCODE
