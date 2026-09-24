param(
  [ValidateSet("deterministic", "hardware", "asr", "polish", "prompts", "phase5", "guided", "auto", "all")]
  [string]$Suite = "deterministic",
  [string]$Models = "",
  [string]$AudioRoots = "",
  [int]$PolishRuns = 3,
  [string]$RewriteModel = "",
  [switch]$Guided,
  [switch]$FailOnGate,
  [switch]$CertifyPhase4,
  [switch]$CertifyPhase5
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

$argsList = @(
  "-m", "devtools.e2e_lab",
  "--config", ".\config.yaml",
  "--cases", ".\e2e\cases.yaml",
  "--suite", $Suite,
  "--polish-runs", [string]$PolishRuns
)
if ($Models.Trim()) {
  $argsList += @("--models", $Models)
}
if ($AudioRoots.Trim()) {
  $argsList += @("--audio-roots", $AudioRoots)
}
if ($RewriteModel.Trim()) {
  $argsList += @("--rewrite-model", $RewriteModel)
}
if ($Guided) {
  $argsList += "--guided"
}
if ($FailOnGate) {
  $argsList += "--fail-on-gate"
}
if ($CertifyPhase4) {
  $argsList += "--certify-phase4"
}
if ($CertifyPhase5) {
  $argsList += "--certify-phase5"
}

& $PythonExe @argsList
exit $LASTEXITCODE
