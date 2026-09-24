param(
    [string]$ExpectedBrowserDomain = "",
    [string]$ExpectedPhrase = "Winsper real speech test",
    [string]$Model = "",
    [double]$RecordSeconds = 3
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

$env:WINSPER_REAL_TESTS = "1"
$env:WINSPER_EXPECTED_BROWSER_DOMAIN = $ExpectedBrowserDomain
$env:WINSPER_EXPECTED_PHRASE = $ExpectedPhrase
$env:WINSPER_RECORD_SECONDS = [string]$RecordSeconds
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue

if ($Model) {
    $env:WINSPER_TEST_MODEL = $Model
}

Write-Host "Winsper real-system tests"
Write-Host "- Close the running Winsper listener to avoid hotkey conflicts."
Write-Host "- Tests will record the configured microphone and send Ctrl+Alt+9."
Write-Host "- Clipboard paste uses a temporary Winsper-owned text field."
if (-not $ExpectedBrowserDomain) {
    Write-Host "- Browser UIA test will skip. Pass -ExpectedBrowserDomain example.com to enable it."
}

& .\.venv\Scripts\python.exe -m pytest -m hardware -s
exit $LASTEXITCODE
