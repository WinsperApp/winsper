param(
  [string]$Case = "",
  [string]$Speaker = "",
  [string]$Category = "",
  [string[]]$Language = @(),
  [switch]$SoloTester,
  [double]$Seconds = 5,
  [switch]$Overwrite,
  [switch]$List
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

$argsList = @(
  "-m", "devtools.e2e_record",
  "--config", ".\config.yaml",
  "--cases", ".\e2e\cases.yaml",
  "--seconds", [string]$Seconds
)
if ($Case.Trim()) {
  $argsList += @("--case", $Case)
}
if ($Speaker.Trim()) {
  $argsList += @("--speaker", $Speaker)
}
if ($Category.Trim()) {
  $argsList += @("--category", $Category)
}
foreach ($languageCode in $Language) {
  if ($languageCode.Trim()) {
    $argsList += @("--language", $languageCode)
  }
}
if ($SoloTester) {
  $argsList += "--solo-tester"
}
if ($Overwrite) {
  $argsList += "--overwrite"
}
if ($List) {
  $argsList += "--list"
}

& .\.venv\Scripts\python.exe @argsList
exit $LASTEXITCODE
