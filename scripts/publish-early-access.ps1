param(
  [string]$Version = "",
  [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Config = Join-Path $Root "scripts\release-wrangler.jsonc"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Npx = (Get-Command npx.cmd -ErrorAction Stop).Source
if (-not $Version) {
  $Version = & $Python -c "from voicepilot import __version__; print(__version__)"
}
if (-not $Version) { throw "Could not resolve the Winsper version." }

$InstallerName = "WinsperSetup-$Version-early-access.exe"
$Installer = Join-Path $Root "dist\installer\$InstallerName"
$Checksum = "$Installer.sha256"
$Notice = Join-Path $Root "dist\installer\EARLY-ACCESS.txt"
$Manifest = Join-Path $Root "dist\installer\early-access.json"
foreach ($Path in @($Installer, $Checksum, $Notice, $Manifest)) {
  if (-not (Test-Path -LiteralPath $Path)) { throw "Missing release artifact: $Path" }
}

$ManifestData = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$ActualHash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ManifestData.channel -ne "early-access") { throw "Manifest is not an Early Access release." }
if ($ManifestData.sha256 -ne $ActualHash) { throw "Manifest checksum does not match the installer." }
if ([int64]$ManifestData.size_bytes -ne (Get-Item -LiteralPath $Installer).Length) {
  throw "Manifest size does not match the installer."
}

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
  if ($LASTEXITCODE -ne 0) { throw "Installer upload failed." }
  & $Npx --yes wrangler@4.137.0 r2 object put "winsper-releases/$InstallerName.sha256" --file $Checksum --remote --config $Config
  if ($LASTEXITCODE -ne 0) { throw "Checksum upload failed." }
  & $Npx --yes wrangler@4.137.0 r2 object put "winsper-releases/EARLY-ACCESS.txt" --file $Notice --remote --config $Config
  if ($LASTEXITCODE -ne 0) { throw "Early Access notice upload failed." }
  & $Npx --yes wrangler@4.137.0 r2 object put "winsper-releases/early-access.json" --file $Manifest --remote --config $Config
  if ($LASTEXITCODE -ne 0) { throw "Early Access manifest upload failed." }
}

if (-not $SkipUpload) {
  $CacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $PublicManifestUrl = "https://winsper.app/updates/early-access.json?release=$Version-$CacheBust"
  $PublicManifest = Invoke-RestMethod -Uri $PublicManifestUrl -Headers @{"Cache-Control"="no-cache"; "Pragma"="no-cache"}
  if ($PublicManifest.sha256 -ne $ActualHash) { throw "The public manifest does not match the release." }
  $Head = Invoke-WebRequest -Uri "https://winsper.app/downloads/$InstallerName" -Method Head -UseBasicParsing
  if ($Head.StatusCode -ne 200 -or [int64]$Head.Headers["Content-Length"] -ne (Get-Item -LiteralPath $Installer).Length) {
    throw "The public installer failed verification."
  }
  $RangeRequest = [System.Net.HttpWebRequest]::Create("https://winsper.app/downloads/$InstallerName")
  $RangeRequest.AddRange(0, 0)
  $RangeResponse = $null
  try {
    $RangeResponse = [System.Net.HttpWebResponse]$RangeRequest.GetResponse()
    if ([int]$RangeResponse.StatusCode -ne 206 -or $RangeResponse.ContentLength -ne 1) {
      throw "The public installer does not support resumable downloads."
    }
  }
  finally {
    if ($null -ne $RangeResponse) { $RangeResponse.Dispose() }
  }
}

Write-Host "Published Winsper $Version Early Access."
Write-Host "Download page: https://winsper.app/download/"
Write-Host "SHA-256: $ActualHash"
