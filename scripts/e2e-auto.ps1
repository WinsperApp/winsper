param(
  [string]$SpeechModels = "parakeet-tdt-0.6b-v2-int8,parakeet-tdt-0.6b-v3-int8,small.en",
  [string]$RewriteModel = "qwen3:8b",
  [int]$PolishRuns = 3
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

$PythonExe = if ($env:WINSPER_PYTHON) {
  $env:WINSPER_PYTHON
} else {
  ".\.venv\Scripts\python.exe"
}
if (-not (Test-Path $PythonExe)) {
  throw "Python runtime not found at '$PythonExe'. Run .\scripts\setup.ps1 or set WINSPER_PYTHON."
}
& $PythonExe --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "Python runtime at '$PythonExe' cannot start. Repair .venv or set WINSPER_PYTHON."
}

Write-Host "Checking optional Ollama service..."
$OllamaTagsUrl = if ($env:WINSPER_TEST_OLLAMA_TAGS_URL) {
  $env:WINSPER_TEST_OLLAMA_TAGS_URL
} else {
  "http://127.0.0.1:11434/api/tags"
}
try {
  $null = Invoke-RestMethod `
    -Uri $OllamaTagsUrl `
    -Method Get `
    -TimeoutSec 5 `
    -ErrorAction Stop
  Write-Host "Ollama service available."
} catch {
  Write-Host "Ollama service unavailable; Ollama-backed cases will be reported as unassessed."
}

Write-Host "Generating labelled Windows TTS coverage corpus..."
& $PythonExe -m devtools.e2e_synthetic `
  --cases .\e2e\cases.yaml `
  --output .\artifacts\e2e\synthetic-corpus
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

$audioRoots = @(
  ".\artifacts\e2e\synthetic-corpus\microsoft-david-desktop",
  ".\artifacts\e2e\synthetic-corpus\microsoft-zira-desktop"
)
if ((Get-ChildItem .\e2e\audio\*.wav -ErrorAction SilentlyContinue).Count -ge 8) {
  $audioRoots = @(".\e2e\audio") + $audioRoots
}

Write-Host "Running unattended Winsper certification..."
& .\scripts\e2e.ps1 `
  -Suite all `
  -Models $SpeechModels `
  -AudioRoots ($audioRoots -join ",") `
  -PolishRuns $PolishRuns `
  -RewriteModel $RewriteModel
exit $LASTEXITCODE
