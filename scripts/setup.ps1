param(
  [string]$PythonVersion = "3.12"
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

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  $Uv = Get-Command uv -ErrorAction SilentlyContinue
  if ($Uv) {
    Invoke-Checked $Uv.Source @("venv", "--python", $PythonVersion, ".venv")
  }
  else {
    $Py = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $Py) { throw "Python $PythonVersion or uv is required to create .venv." }
    Invoke-Checked $Py.Source @("-$PythonVersion", "-m", "venv", ".venv")
  }
}
$VenvPython = ".\.venv\Scripts\python.exe"
Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", "requirements-lock.txt")
Invoke-Checked $VenvPython @("-m", "pip", "install", "-e", ".", "--no-deps")

if (-not (Test-Path .\config.yaml)) {
  Copy-Item .\config.example.yaml .\config.yaml
}

Write-Host ""
Write-Host "Winsper setup complete."
Write-Host "Run: .\scripts\run.ps1"
