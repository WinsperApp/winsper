param(
  [switch]$NoHud,
  [switch]$SkipSetup,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

$argsList = @("-m", "voicepilot", "--config", ".\config.yaml")
if ($NoHud) {
  $argsList += "--no-hud"
}
if ($SkipSetup) {
  $argsList += "--skip-setup"
}
if ($ExtraArgs) {
  $argsList += $ExtraArgs
}

& .\.venv\Scripts\python.exe @argsList
