param(
  [string]$PythonPath = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

function Invoke-Checked {
  param(
    [string]$FilePath,
    [string[]]$Arguments
  )

  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath failed with exit code $LASTEXITCODE"
  }
}

if (-not (Test-Path $PythonPath)) {
  throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

Invoke-Checked "uv" @("pip", "install", "--python", $PythonPath, "-r", "requirements-parakeet.txt")

Write-Host ""
Write-Host "Parakeet support installed."
Write-Host "Next: download parakeet-tdt-0.6b-v2-int8 from Winsper Settings > Advanced > Models."
