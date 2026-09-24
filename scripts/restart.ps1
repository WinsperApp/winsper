$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

& .\.venv\Scripts\python.exe -m voicepilot --config .\config.yaml --restart
