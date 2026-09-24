param(
  [switch]$Installer,
  [switch]$EarlyAccess,
  [switch]$UnsignedPublic,
  [string]$CertificateThumbprint = "",
  [string]$TimestampUrl = "http://timestamp.digicert.com",
  [string]$Publisher = "Winsper",
  [string]$EarlyAccessBaseUrl = "https://winsper.app/downloads/",
  [string]$EarlyAccessDownloadPageUrl = "https://winsper.app/download/",
  [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$UnsignedMessage = "Unsigned builds require an explicit distribution channel."
if (-not $CertificateThumbprint -and -not $EarlyAccess -and -not $UnsignedPublic) {
  throw "$UnsignedMessage Pass -UnsignedPublic, pass -EarlyAccess, or provide -CertificateThumbprint."
}
if (@($CertificateThumbprint, $EarlyAccess, $UnsignedPublic).Where({ [bool]$_ }).Count -gt 1) {
  throw "Choose one release path: signed production, unsigned public, or unsigned Early Access."
}
if (($EarlyAccess -or $UnsignedPublic) -and -not $Installer) {
  throw "Unsigned releases require -Installer so users receive one versioned artifact."
}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$HostLocalAppData = $env:LOCALAPPDATA
if (-not (Test-Path $Python)) {
  throw "Missing project runtime: $Python. Run .\scripts\setup.ps1 first or pass -Python."
}

New-Item -ItemType Directory -Force -Path ".\build" | Out-Null
& $Python -c "from voicepilot.branding import create_app_icon_image; create_app_icon_image(256).save(r'build/winsper.ico', sizes=[(16,16),(20,20),(24,24),(32,32),(40,40),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw "Could not create Windows icon." }
& ".\scripts\build-native-audio.ps1" -Quiet
if ($LASTEXITCODE -ne 0) { throw "Could not build the native Windows microphone component." }
& $Python .\scripts\prepare_embedded_polish_runtime.py `
  --output .\build\embedded-polish-runtime `
  --cache-root .\build\embedded-polish-cache
if ($LASTEXITCODE -ne 0) { throw "Could not prepare the embedded Polish runtime." }

$TestRoot = Join-Path $Root ("build\test-" + [guid]::NewGuid().ToString("N"))
$OriginalTemp = [Environment]::GetEnvironmentVariable("TEMP", "Process")
$OriginalTmp = [Environment]::GetEnvironmentVariable("TMP", "Process")
$OriginalLocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA", "Process")
$OriginalQtPlatform = [Environment]::GetEnvironmentVariable("QT_QPA_PLATFORM", "Process")
try {
  New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
  $env:TEMP = $TestRoot
  $env:TMP = $TestRoot
  $env:LOCALAPPDATA = $TestRoot
  $env:QT_QPA_PLATFORM = "offscreen"
  & $Python .\scripts\check_architecture.py
  if ($LASTEXITCODE -ne 0) { throw "Architecture gate failed." }
  & $Python -m pytest -q -p no:cacheprovider --basetemp (Join-Path $TestRoot "pytest")
  if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
  & $Python -m ruff check .
  if ($LASTEXITCODE -ne 0) { throw "Lint failed." }
}
finally {
  [Environment]::SetEnvironmentVariable("TEMP", $OriginalTemp, "Process")
  [Environment]::SetEnvironmentVariable("TMP", $OriginalTmp, "Process")
  [Environment]::SetEnvironmentVariable("LOCALAPPDATA", $OriginalLocalAppData, "Process")
  [Environment]::SetEnvironmentVariable("QT_QPA_PLATFORM", $OriginalQtPlatform, "Process")

  if (Test-Path -LiteralPath $TestRoot) {
    $ResolvedBuildRoot = (Resolve-Path -LiteralPath (Join-Path $Root "build")).Path
    $ResolvedTestRoot = (Resolve-Path -LiteralPath $TestRoot).Path
    $ExpectedPrefix = $ResolvedBuildRoot + [IO.Path]::DirectorySeparatorChar + "test-"
    if (-not $ResolvedTestRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to remove unexpected test directory: $ResolvedTestRoot"
    }
    Remove-Item -LiteralPath $ResolvedTestRoot -Recurse -Force
  }
}

& $Python -m PyInstaller --noconfirm --clean .\winsper.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
$ArchiveModules = & $Python -m PyInstaller.utils.cliutils.archive_viewer -r -b .\dist\Winsper\Winsper.exe
if ($LASTEXITCODE -ne 0) { throw "Could not inspect frozen Python modules." }
if (@($ArchiveModules | Where-Object { $_.Trim() -eq "mouseinfo" }).Count) {
  throw "Unused GPL-licensed MouseInfo utility was bundled into Winsper."
}

$PackageRoot = (Resolve-Path ".\dist\Winsper").Path
$Exe = (Resolve-Path (Join-Path $PackageRoot "Winsper.exe")).Path
$InternalRoot = Join-Path $PackageRoot "_internal"
$EmbeddedLlamaRoot = Join-Path $InternalRoot "voicepilot\runtime\llama"
$EmbeddedLlamaServer = Join-Path $EmbeddedLlamaRoot "llama-server.exe"
$NativeAudioDll = Join-Path $InternalRoot "voicepilot\runtime\audio\winsper_audio.dll"

if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
  throw "Packaged Winsper.exe is missing."
}
if (-not (Test-Path -LiteralPath $EmbeddedLlamaServer -PathType Leaf)) {
  throw "Packaged embedded llama-server.exe is missing."
}
if (-not (Test-Path -LiteralPath $NativeAudioDll -PathType Leaf)) {
  throw "Packaged native Windows microphone component is missing."
}
foreach ($Notice in @("LICENSE", "THIRD_PARTY_NOTICES.md", "LGPL_SOURCE_OFFER.md", "licenses\COPYING", "licenses\COPYING.LGPL")) {
  if (-not (Test-Path -LiteralPath (Join-Path $InternalRoot $Notice) -PathType Leaf)) {
    throw "Packaged distribution notice is missing: $Notice"
  }
}

$ForbiddenDirectories = Get-ChildItem -LiteralPath $PackageRoot -Directory -Recurse |
  Where-Object {
    $RelativePath = $_.FullName.Substring($PackageRoot.Length + 1)
    $Segments = @($RelativePath -split "[\\/]")
    $PayloadIndex = if ($Segments[0].Equals("_internal", [StringComparison]::OrdinalIgnoreCase)) { 1 } else { 0 }
    $PayloadIndex -lt $Segments.Count -and
      @("test", "tests", "scripts", "e2e", "logs", "history", "models") -contains $Segments[$PayloadIndex].ToLowerInvariant()
  }
if ($ForbiddenDirectories) {
  $Names = ($ForbiddenDirectories | ForEach-Object { $_.FullName.Substring($PackageRoot.Length + 1) }) -join ", "
  throw "Development or user-data directories leaked into the package: $Names"
}

$AllowedOnnx = "_internal\faster_whisper\assets\silero_vad_v6.onnx"
$ForbiddenPayloads = Get-ChildItem -LiteralPath $PackageRoot -File -Recurse | Where-Object {
  $RelativePath = $_.FullName.Substring($PackageRoot.Length + 1)
  $Name = $_.Name.ToLowerInvariant()
  $Extension = $_.Extension.ToLowerInvariant()
  $Name -in @("config.yaml", "config.yml", "config.example.yaml", "history.jsonl", "history.enc") -or
    $Extension -in @(".log", ".jsonl", ".bin", ".gguf", ".safetensors", ".ckpt", ".pt", ".pth") -or
    ($Extension -eq ".onnx" -and -not $RelativePath.Equals($AllowedOnnx, [StringComparison]::OrdinalIgnoreCase))
}
if ($ForbiddenPayloads) {
  $Names = ($ForbiddenPayloads | ForEach-Object { $_.FullName.Substring($PackageRoot.Length + 1) }) -join ", "
  throw "Config, history, log, or model payloads leaked into the package: $Names"
}

$EmbeddedDllNames = @(
  Get-ChildItem -LiteralPath $EmbeddedLlamaRoot -File -Filter "*.dll" |
    ForEach-Object { $_.Name.ToLowerInvariant() }
)
$RedundantLlamaDlls = Get-ChildItem -LiteralPath $InternalRoot -File -Filter "*.dll" |
  Where-Object { $EmbeddedDllNames -contains $_.Name.ToLowerInvariant() }
if ($RedundantLlamaDlls) {
  throw "Redundant root llama runtime DLLs were packaged: $(($RedundantLlamaDlls.Name) -join ', ')"
}

function Invoke-HiddenSmoke {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [Parameter(Mandatory = $true)][string]$Name,
    [int]$TimeoutSeconds = 20
  )

  $Process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WindowStyle Hidden -PassThru
  try {
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
      Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
      $Process.WaitForExit()
      throw "$Name smoke test timed out after $TimeoutSeconds seconds."
    }
    if ($Process.ExitCode -ne 0) {
      throw "$Name smoke test failed with exit code $($Process.ExitCode)."
    }
  }
  finally {
    if (-not $Process.HasExited) {
      Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
    $Process.Dispose()
  }
}

$SmokeRoot = Join-Path $Root ("build\package-smoke-" + [guid]::NewGuid().ToString("N"))
try {
  New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
  $SmokeConfig = Join-Path $SmokeRoot "config.yaml"
  Invoke-HiddenSmoke `
    -FilePath $Exe `
    -ArgumentList @("--config", "`"$SmokeConfig`"", "--print-config") `
    -Name "Packaged Winsper --print-config"
  Invoke-HiddenSmoke `
    -FilePath $EmbeddedLlamaServer `
    -ArgumentList @("--version") `
    -Name "Embedded llama-server --version"
}
finally {
  if (Test-Path -LiteralPath $SmokeRoot) {
    $ResolvedBuildRoot = (Resolve-Path -LiteralPath (Join-Path $Root "build")).Path
    $ResolvedSmokeRoot = (Resolve-Path -LiteralPath $SmokeRoot).Path
    $ExpectedPrefix = $ResolvedBuildRoot + [IO.Path]::DirectorySeparatorChar + "package-smoke-"
    if (-not $ResolvedSmokeRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to remove unexpected smoke-test directory: $ResolvedSmokeRoot"
    }
    Remove-Item -LiteralPath $ResolvedSmokeRoot -Recurse -Force
  }
}

$PackageFiles = @(Get-ChildItem -LiteralPath $PackageRoot -File -Recurse)
$PackageBytes = [int64](($PackageFiles | Measure-Object -Property Length -Sum).Sum)
Write-Host "Package audit passed: $($PackageFiles.Count) files, $PackageBytes bytes."

if ($CertificateThumbprint) {
  $SignTool = Get-Command signtool.exe -ErrorAction Stop
  & $SignTool.Source sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $Exe
  if ($LASTEXITCODE -ne 0) { throw "Executable signing failed." }
}

if ($Installer) {
  $Compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if (-not $Compiler) {
    $CompilerPaths = @(
      (Join-Path $HostLocalAppData "Programs\Inno Setup 6\ISCC.exe"),
      (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
      (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if (-not $CompilerPaths) {
      throw "Inno Setup 6 was not found. Install JRSoftware.InnoSetup with winget."
    }
    $CompilerPath = @($CompilerPaths)[0]
  } else {
    $CompilerPath = $Compiler.Source
  }
  $Version = & $Python -c "from voicepilot import __version__; print(__version__)"
  if (-not $Version) { throw "Could not resolve Winsper version." }
  $CompilerArgs = @("/DMyAppVersion=$Version", "/DMyAppPublisher=$Publisher")
  if ($EarlyAccess) {
    $CompilerArgs += "/DMyAppReleaseSuffix=-early-access"
  }
  $CompilerArgs += ".\installer\Winsper.iss"
  & $CompilerPath @CompilerArgs
  if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }
  if ($CertificateThumbprint) {
    $InstallerExe = Get-ChildItem ".\dist\installer\WinsperSetup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    & (Get-Command signtool.exe -ErrorAction Stop).Source sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $InstallerExe.FullName
    if ($LASTEXITCODE -ne 0) { throw "Installer signing failed." }
  }
}

if ($EarlyAccess) {
  $InstallerPath = ".\dist\installer\WinsperSetup-$Version-early-access.exe"
  if (-not (Test-Path -LiteralPath $InstallerPath)) { throw "Early Access installer was not produced." }
  $InstallerExe = Get-Item -LiteralPath $InstallerPath

  $Artifacts = @((Get-Item $Exe), $InstallerExe)
  foreach ($Artifact in $Artifacts) {
    $Signature = Get-AuthenticodeSignature -LiteralPath $Artifact.FullName
    if ($Signature.Status -ne "NotSigned") {
      throw "Unexpected signature state for $($Artifact.Name): $($Signature.Status)"
    }
  }

  Remove-Item ".\dist\installer\stable.json" -Force -ErrorAction SilentlyContinue
  $Hash = (Get-FileHash -LiteralPath $InstallerExe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $ChecksumPath = "$($InstallerExe.FullName).sha256"
  Set-Content -LiteralPath $ChecksumPath -Value "$Hash *$($InstallerExe.Name)" -Encoding ascii

  $NoticePath = Join-Path $InstallerExe.DirectoryName "EARLY-ACCESS.txt"
  @"
Winsper $Version - Controlled Early Access

This installer is intentionally unsigned while Winsper's Microsoft Store
publisher review is pending. Windows may display an Unknown publisher or
Microsoft Defender SmartScreen warning.

Download Winsper only from https://winsper.app and compare the installer's
SHA-256 value with the checksum published beside the download. Never disable
antivirus protection to install Winsper.

Winsper can notify you when a new Early Access version is available, but it
will never silently download or run an unsigned installer. Future releases
must be downloaded manually from https://winsper.app/download/ until Winsper
is distributed through Microsoft Store or uses a trusted signing certificate.

SHA-256
$Hash
"@ | Set-Content -LiteralPath $NoticePath -Encoding utf8

  $ManifestPath = Join-Path $InstallerExe.DirectoryName "early-access.json"
  & $Python .\scripts\release_manifest.py $InstallerExe.FullName `
    --version $Version `
    --base-url $EarlyAccessBaseUrl `
    --download-page-url $EarlyAccessDownloadPageUrl `
    --channel early-access `
    --notes "Adds a reliable embedded Polish runtime with safe CPU fallback." `
    --output $ManifestPath
  if ($LASTEXITCODE -ne 0) { throw "Could not generate the Early Access manifest." }

  Write-Host "Early Access installer: $($InstallerExe.FullName)"
  Write-Host "SHA-256: $Hash"
  Write-Host "Checksum: $ChecksumPath"
  Write-Host "Notice: $NoticePath"
  Write-Host "Manifest: $ManifestPath"
}

if ($UnsignedPublic) {
  $InstallerPath = ".\dist\installer\WinsperSetup-$Version.exe"
  if (-not (Test-Path -LiteralPath $InstallerPath)) { throw "Unsigned public installer was not produced." }
  $InstallerExe = Get-Item -LiteralPath $InstallerPath

  foreach ($Artifact in @((Get-Item $Exe), $InstallerExe)) {
    $Signature = Get-AuthenticodeSignature -LiteralPath $Artifact.FullName
    if ($Signature.Status -ne "NotSigned") {
      throw "Unexpected signature state for $($Artifact.Name): $($Signature.Status)"
    }
  }

  $Hash = (Get-FileHash -LiteralPath $InstallerExe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $ChecksumPath = "$($InstallerExe.FullName).sha256"
  Set-Content -LiteralPath $ChecksumPath -Value "$Hash *$($InstallerExe.Name)" -Encoding ascii

  $NoticePath = Join-Path $InstallerExe.DirectoryName "UNSIGNED.txt"
  @"
Winsper $Version

This installer is distributed directly by Winsper and is not code-signed.
Windows may display an Unknown publisher or Microsoft Defender SmartScreen
notice. Download Winsper only from https://winsper.app and compare the
installer SHA-256 with the checksum published beside the download. Never
disable antivirus protection to install Winsper.

Winsper update notifications open the official download page. Winsper never
silently downloads or runs an unsigned installer.

SHA-256
$Hash
"@ | Set-Content -LiteralPath $NoticePath -Encoding utf8

  $ManifestPath = Join-Path $InstallerExe.DirectoryName "stable.json"
  & $Python .\scripts\release_manifest.py $InstallerExe.FullName `
    --version $Version `
    --base-url $EarlyAccessBaseUrl `
    --download-page-url $EarlyAccessDownloadPageUrl `
    --channel stable `
    --notes "Improves first-run setup, model selection, and selected-text Polish feedback." `
    --output $ManifestPath
  if ($LASTEXITCODE -ne 0) { throw "Could not generate the public release manifest." }

  Write-Host "Unsigned public installer: $($InstallerExe.FullName)"
  Write-Host "SHA-256: $Hash"
  Write-Host "Checksum: $ChecksumPath"
  Write-Host "Notice: $NoticePath"
  Write-Host "Manifest: $ManifestPath"
}

Write-Host "Release output: $Exe"
