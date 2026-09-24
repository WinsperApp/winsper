param(
    [string]$Config = ".\config.yaml",
    [ValidateSet("source", "package")]
    [string]$Mode = "source",
    [ValidateRange(1, 100)]
    [int]$Cycles = 5,
    [string]$Output = ".\artifacts\certification\release-candidate",
    [string]$PackageExe = ".\dist\Winsper\Winsper.exe"
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

$PythonExe = if ($env:WINSPER_PYTHON) {
    $env:WINSPER_PYTHON
} else {
    ".\.venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python runtime not found at '$PythonExe'. Run .\scripts\setup.ps1 or set WINSPER_PYTHON."
}
& $PythonExe --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Python runtime at '$PythonExe' cannot start. Repair .venv or set WINSPER_PYTHON."
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw "Winsper config not found at '$Config'."
}
if ($Mode -eq "package" -and -not (Test-Path -LiteralPath $PackageExe -PathType Leaf)) {
    throw "Packaged Winsper executable not found at '$PackageExe'. Run .\scripts\build-release.ps1 first."
}

$argsList = @(
    "-m", "devtools.release_candidate",
    "--config", $Config,
    "--mode", $Mode,
    "--cycles", [string]$Cycles,
    "--output", $Output
)
if ($Mode -eq "package") {
    $argsList += @("--package-exe", $PackageExe)
}

Write-Host "Winsper release-candidate certification"
Write-Host "- Mode: $Mode"
Write-Host "- Cycles: $Cycles"
Write-Host "- Output: $Output"

& $PythonExe @argsList
exit $LASTEXITCODE
