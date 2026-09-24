$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

if (Test-Path .\.venv\Scripts\python.exe) {
  & .\.venv\Scripts\python.exe -m voicepilot --config .\config.yaml --stop
  Start-Sleep -Seconds 2
}

$matches = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -in @("python.exe", "pythonw.exe") -and
  $_.CommandLine -like "*-m voicepilot*" -and
  $_.CommandLine -notlike "*--settings*" -and
  $_.CommandLine -notlike "*--history*" -and
  $_.CommandLine -notlike "*--preview*"
}

if (-not $matches) {
  Write-Host "Winsper stopped."
  exit 0
}

foreach ($proc in $matches) {
  try {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    Write-Host "Stopped Winsper process $($proc.ProcessId)."
  } catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
    Write-Host "Winsper process $($proc.ProcessId) already exited."
  }
}
