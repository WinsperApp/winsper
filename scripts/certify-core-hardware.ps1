param(
    [int]$MicStartCycles = 500,
    [double]$MaxMicStartP95Ms = 100,
    [double]$MaxFirstFrameP95Ms = 100,
    [double]$MinMicSuccessRate = 0.998
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

$env:WINSPER_REAL_TESTS = "1"
$env:WINSPER_MIC_START_CYCLES = [string]$MicStartCycles
$env:WINSPER_MAX_MIC_START_MS = [string]$MaxMicStartP95Ms
$env:WINSPER_MAX_FIRST_FRAME_MS = [string]$MaxFirstFrameP95Ms
$env:WINSPER_MIN_MIC_SUCCESS_RATE = [string]$MinMicSuccessRate
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue

$ArtifactRoot = Join-Path $AppRoot "artifacts\certification"
New-Item -ItemType Directory -Force $ArtifactRoot | Out-Null

Write-Host "Winsper unattended core hardware certification"
Write-Host "- Close the running Winsper listener to avoid microphone and hotkey conflicts."
Write-Host "- The temporary test fields may briefly take focus and move the pointer."

$Tests = @(
    "tests/integration/test_real_windows.py::test_real_microphone_repeated_starts_meet_release_gate",
    "tests/integration/test_real_windows.py::test_real_clipboard_paste_and_restore",
    "tests/integration/test_real_windows.py::test_real_rich_clipboard_paste_and_restore",
    "tests/integration/test_real_windows.py::test_real_target_change_never_pastes_into_new_window",
    "tests/integration/test_real_windows.py::test_real_polish_selection_snapshot_captures_focused_text",
    "tests/integration/test_real_windows.py::test_real_registered_hotkey_receives_system_events"
)

& .\.venv\Scripts\python.exe -m pytest -q -s `
    "--junitxml=$ArtifactRoot\core-hardware.xml" `
    $Tests
exit $LASTEXITCODE
