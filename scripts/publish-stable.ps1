param(
  [string]$Version = "",
  [Parameter(Mandatory = $true)][string]$Publisher,
  [switch]$AllowUnsigned,
  [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Config = Join-Path $Root "scripts\release-wrangler.jsonc"
$Python = if ($env:WINSPER_PYTHON) {
  $env:WINSPER_PYTHON
} else {
  Join-Path $Root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
  throw "Python runtime not found at '$Python'. Run .\scripts\setup.ps1 or set WINSPER_PYTHON."
}
& $Python --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "Python runtime at '$Python' cannot start. Repair .venv or set WINSPER_PYTHON."
}
$Npx = (Get-Command npx.cmd -ErrorAction Stop).Source
if (-not $Version) {
  $Version = & $Python -c "from voicepilot import __version__; print(__version__)"
}
if (-not $Version) { throw "Could not resolve the Winsper version." }

$InstallerName = "WinsperSetup-$Version.exe"
$Installer = Join-Path $Root "dist\installer\$InstallerName"
$Manifest = Join-Path $Root "dist\installer\stable.json"
foreach ($Path in @($Installer, $Manifest, $Config)) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing stable release input: $Path" }
}

$SourceVersion = & $Python -c "from voicepilot import __version__; print(__version__)"
if ($SourceVersion -ne $Version) { throw "Version mismatch: source=$SourceVersion requested=$Version" }
$ManifestData = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$ActualHash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
$ActualSize = (Get-Item -LiteralPath $Installer).Length
if ($ManifestData.version -ne $Version) { throw "Manifest version does not match the release." }
if ($ManifestData.channel -ne "stable") { throw "Manifest is not a stable release." }
if ($ManifestData.sha256 -ne $ActualHash) { throw "Manifest checksum does not match the installer." }
if ([int64]$ManifestData.size_bytes -ne $ActualSize) { throw "Manifest size does not match the installer." }
if ($ManifestData.installer_url -ne "https://winsper.app/downloads/$InstallerName") {
  throw "Stable installer URL must use the immutable official Winsper path."
}

$Signature = Get-AuthenticodeSignature -LiteralPath $Installer
if ($AllowUnsigned) {
  if ($Signature.Status -ne "NotSigned") {
    throw "Unsigned publishing requires an installer with NotSigned status."
  }
  $UnsignedNotice = Join-Path $Root "dist\installer\UNSIGNED.txt"
  if (-not (Test-Path -LiteralPath $UnsignedNotice -PathType Leaf)) {
    throw "Unsigned release notice is missing."
  }
} else {
  if ($Signature.Status -ne "Valid" -or -not $Signature.SignerCertificate) {
    throw "Stable installer must have a valid Authenticode signature."
  }
  if ($Signature.SignerCertificate.Subject -notlike "*$Publisher*") {
    throw "Stable installer publisher does not match '$Publisher'."
  }
}

$Checksum = "$Installer.sha256"
Set-Content -LiteralPath $Checksum -Value "$ActualHash *$InstallerName" -Encoding ascii

if (-not $SkipUpload) {
  $PublicInstallerUrl = "https://winsper.app/downloads/$InstallerName"
  $ExistingStatus = 0
  try {
    $Existing = Invoke-WebRequest -Uri $PublicInstallerUrl -Method Head -UseBasicParsing
    $ExistingStatus = [int]$Existing.StatusCode
  }
  catch {
    if ($null -ne $_.Exception.Response) {
      $ExistingStatus = [int]$_.Exception.Response.StatusCode
    } else {
      throw
    }
  }
  if ($ExistingStatus -eq 200) { throw "Immutable release already exists: $PublicInstallerUrl" }
  if ($ExistingStatus -ne 404) { throw "Could not prove release path is unused (HTTP $ExistingStatus)." }

  & $Npx --yes wrangler@4.137.0 r2 object put "winsper-releases/$InstallerName" --file $Installer --remote --config $Config
  if ($LASTEXITCODE -ne 0) { throw "Stable installer upload failed." }
  & $Npx --yes wrangler@4.137.0 r2 object put "winsper-releases/$InstallerName.sha256" --file $Checksum --remote --config $Config
  if ($LASTEXITCODE -ne 0) { throw "Stable checksum upload failed." }
  if ($AllowUnsigned) {
    & $Npx --yes wrangler@4.137.0 r2 object put "winsper-releases/UNSIGNED.txt" --file $UnsignedNotice --remote --config $Config
    if ($LASTEXITCODE -ne 0) { throw "Unsigned release notice upload failed." }
  }
  & $Npx --yes wrangler@4.137.0 r2 object put "winsper-releases/stable.json" --file $Manifest --remote --config $Config
  if ($LASTEXITCODE -ne 0) { throw "Stable update manifest upload failed." }
}

if (-not $SkipUpload) {
  $CacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $PublicManifest = Invoke-RestMethod -Uri "https://winsper.app/updates/stable.json?release=$Version-$CacheBust" -Headers @{"Cache-Control"="no-cache"; "Pragma"="no-cache"}
  if ($PublicManifest.sha256 -ne $ActualHash -or $PublicManifest.version -ne $Version) {
    throw "The public stable manifest does not match the release."
  }
  $Head = Invoke-WebRequest -Uri "https://winsper.app/downloads/$InstallerName" -Method Head -UseBasicParsing
  $PublicSize = [int64](@($Head.Headers["Content-Length"])[0])
  if ($Head.StatusCode -ne 200 -or $PublicSize -ne $ActualSize) {
    throw "The public stable installer failed verification."
  }
}

Write-Host "Published Winsper $Version."
Write-Host "SHA-256: $ActualHash"
