param(
  [string]$Model = "small.en",
  [string]$Models = "",
  [string]$Device = "cpu",
  [string]$ComputeType = "int8",
  [int]$Seconds = 5,
  [int]$WarmRuns = 5
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

$argsList = @(
  "-m", "voicepilot.benchmark",
  "--config", ".\config.yaml",
  "--device", $Device,
  "--compute-type", $ComputeType,
  "--seconds", $Seconds,
  "--warm-runs", $WarmRuns
)
if ($Models.Trim()) {
  $argsList += @("--models", $Models)
} else {
  $argsList += @("--model", $Model)
}

& .\.venv\Scripts\python.exe @argsList
