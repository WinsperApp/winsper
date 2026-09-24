param(
  [switch]$Force,
  [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Root "native\winsper_audio\winsper_audio.cpp"
$OutputDirectory = Join-Path $Root "build\native-audio"
$Output = Join-Path $OutputDirectory "winsper_audio.dll"
$VsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$Installation = if (Test-Path -LiteralPath $VsWhere -PathType Leaf) {
  & $VsWhere -latest -products "*" -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}
$VcVars = if ($Installation) {
  Join-Path ($Installation | Select-Object -First 1) "VC\Auxiliary\Build\vcvars64.bat"
}

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
  throw "Native audio source is missing: $Source"
}
if (-not $VcVars -or -not (Test-Path -LiteralPath $VcVars -PathType Leaf)) {
  throw "Visual Studio C++ Build Tools are required to build Winsper audio."
}

if (-not $Force -and (Test-Path -LiteralPath $Output -PathType Leaf)) {
  $SourceWrite = (Get-Item -LiteralPath $Source).LastWriteTimeUtc
  $OutputWrite = (Get-Item -LiteralPath $Output).LastWriteTimeUtc
  if ($OutputWrite -ge $SourceWrite) {
    if (-not $Quiet) { Write-Host "Native Winsper audio is current: $Output" }
    return
  }
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$Object = Join-Path $OutputDirectory "winsper_audio.obj"
$Command = 'call "{0}" >nul && cl.exe /nologo /LD /O2 /EHsc /std:c++17 /MT /DUNICODE /D_UNICODE /Fo:"{1}" /Fe:"{2}" "{3}" /link ole32.lib uuid.lib propsys.lib' -f $VcVars, $Object, $Output, $Source
& "$env:ComSpec" /d /s /c $Command
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Output -PathType Leaf)) {
  throw "Could not build native Winsper audio."
}
if (-not $Quiet) { Write-Host "Built native Winsper audio: $Output" }
