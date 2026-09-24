param(
  [Parameter(Mandatory = $true)]
  [string]$InstallerPath,
  [switch]$AllowDestructiveCurrentUserTest,
  [switch]$PreserveUserData
)

$ErrorActionPreference = "Stop"
if (-not $AllowDestructiveCurrentUserTest) {
  throw "Installer lifecycle validation changes Winsper installation registration and shortcuts. Run it only on a disposable CI/VM account and explicitly pass -AllowDestructiveCurrentUserTest."
}

$Installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$TemporaryRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$AuditRoot = Join-Path $TemporaryRoot ("winsper-lifecycle-" + [guid]::NewGuid().ToString("N"))
$InstallRoot = Join-Path $AuditRoot "Winsper"
$RoamingRoot = Join-Path $env:APPDATA "Winsper"
$LocalRoot = Join-Path $env:LOCALAPPDATA "Winsper"
$RoamingRootExisted = Test-Path -LiteralPath $RoamingRoot
$LocalRootExisted = Test-Path -LiteralPath $LocalRoot
$MarkerName = "lifecycle-audit-$([guid]::NewGuid().ToString('N')).txt"
$MarkerValue = "Winsper installer lifecycle marker"
$RoamingMarker = Join-Path $RoamingRoot $MarkerName
$LocalMarker = Join-Path $LocalRoot $MarkerName
$StartupScript = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Winsper.vbs"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Winsper.lnk"
$ProgramsShortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Winsper.lnk"
$UninstallKey = "Software\Microsoft\Windows\CurrentVersion\Uninstall\{13D45A8C-61C1-4C74-A09E-8863EBF61391}_is1"
$UninstallRegistryPaths = @(
  "Registry::HKEY_CURRENT_USER\$UninstallKey",
  "Registry::HKEY_LOCAL_MACHINE\$UninstallKey",
  "Registry::HKEY_LOCAL_MACHINE\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{13D45A8C-61C1-4C74-A09E-8863EBF61391}_is1"
)
$ExistingUninstallRegistration = $UninstallRegistryPaths | Where-Object { Test-Path -LiteralPath $_ }
if ($ExistingUninstallRegistration) {
  throw "A real Winsper installation is already registered. Use a disposable test machine; no changes were made. Found: $($ExistingUninstallRegistration -join ', ')"
}
$ExistingShellArtifact = @($StartupScript, $DesktopShortcut, $ProgramsShortcut) |
  Where-Object { Test-Path -LiteralPath $_ }
if ($ExistingShellArtifact) {
  throw "Existing Winsper shortcuts or startup launchers make this account unsafe for lifecycle validation. Use a disposable test machine; no changes were made. Found: $($ExistingShellArtifact -join ', ')"
}
if (Test-Path -LiteralPath $AuditRoot) {
  throw "Refusing to reuse an existing lifecycle audit root: $AuditRoot"
}
if (-not $PreserveUserData -and ($RoamingRootExisted -or $LocalRootExisted)) {
  throw "Purge validation requires Winsper user-data roots to be absent before the test. Use a clean disposable account; no changes were made."
}

$UninstallCompleted = $false
$LifecycleError = $null
$CleanupErrors = [Collections.Generic.List[string]]::new()
$Mode = if ($PreserveUserData) { "preserved-user-data" } else { "purged-user-data" }

function Assert-PathMissing([string]$Path, [string]$Label) {
  if (Test-Path -LiteralPath $Path) { throw "$Label was not removed: $Path" }
}

function Remove-OwnedPath([string]$Path, [string]$Label, [switch]$Recurse) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  if ($Recurse) {
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
  } else {
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
  }
  if (Test-Path -LiteralPath $Path) {
    throw "$Label cleanup failed: $Path"
  }
}

function Assert-MarkerPreserved([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label was not preserved: $Path"
  }
  $Actual = Get-Content -LiteralPath $Path -Raw
  if ($Actual.TrimEnd() -ne $MarkerValue) {
    throw "$Label content changed during uninstall: $Path"
  }
}

try {
  New-Item -ItemType Directory -Force -Path $AuditRoot | Out-Null
  $InstallProcess = Start-Process -FilePath $Installer `
    -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$InstallRoot`"" `
    -PassThru -Wait
  if ($InstallProcess.ExitCode -ne 0) {
    throw "Installer failed with exit code $($InstallProcess.ExitCode)."
  }
  $Exe = Join-Path $InstallRoot "Winsper.exe"
  $Uninstaller = Join-Path $InstallRoot "unins000.exe"
  if (-not (Test-Path -LiteralPath $Exe)) { throw "Winsper.exe was not installed." }
  if (-not (Test-Path -LiteralPath $Uninstaller)) { throw "Inno uninstaller was not installed." }

  $Version = (Get-Item -LiteralPath $Exe).VersionInfo
  if ($Version.ProductName -ne "Winsper" -or $Version.OriginalFilename -ne "Winsper.exe") {
    throw "Packaged executable identity is incorrect."
  }

  $Process = Start-Process -FilePath $Exe -ArgumentList "--help" -PassThru -Wait
  if ($Process.ExitCode -ne 0) { throw "Packaged Winsper command line failed with exit code $($Process.ExitCode)." }

  New-Item -ItemType Directory -Force -Path $RoamingRoot, $LocalRoot | Out-Null
  Set-Content -LiteralPath $RoamingMarker -Value $MarkerValue
  Set-Content -LiteralPath $LocalMarker -Value $MarkerValue

  $UninstallArguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
  if (-not $PreserveUserData) { $UninstallArguments += " /PURGEUSERDATA" }
  $UninstallProcess = Start-Process -FilePath $Uninstaller -ArgumentList $UninstallArguments -PassThru -Wait
  if ($UninstallProcess.ExitCode -ne 0) {
    throw "Uninstaller failed with exit code $($UninstallProcess.ExitCode)."
  }
  $UninstallCompleted = $true

  Assert-PathMissing $InstallRoot "Install directory"
  if (-not $PreserveUserData) {
    Assert-PathMissing $RoamingMarker "Roaming user data marker"
    Assert-PathMissing $LocalMarker "Local user data marker"
    Assert-PathMissing $RoamingRoot "Roaming user data"
    Assert-PathMissing $LocalRoot "Local user data"
  } else {
    Assert-MarkerPreserved $RoamingMarker "Roaming user data marker"
    Assert-MarkerPreserved $LocalMarker "Local user data marker"
  }
  Assert-PathMissing $RecoveryPath "Licence recovery file"
  Assert-PathMissing $RecoveryInvalidationPath "Licence recovery invalidation marker"
  Assert-PathMissing $StartupScript "Startup launcher"
  Assert-PathMissing $DesktopShortcut "Desktop shortcut"
  Assert-PathMissing $ProgramsShortcut "Start menu shortcut"

  if ($UninstallRegistryPaths | Where-Object { Test-Path -LiteralPath $_ }) {
    throw "Uninstall registration remains in the registry."
  }
}
catch {
  $LifecycleError = $_
}
finally {
  if (-not $UninstallCompleted) {
    try {
      $RecoveryUninstaller = Join-Path $InstallRoot "unins000.exe"
      if (Test-Path -LiteralPath $RecoveryUninstaller -PathType Leaf) {
        $RecoveryProcess = Start-Process -FilePath $RecoveryUninstaller `
          -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" `
          -PassThru -Wait
        if ($RecoveryProcess.ExitCode -ne 0) {
          throw "Recovery uninstaller failed with exit code $($RecoveryProcess.ExitCode)."
        }
      }
    } catch {
      [void]$CleanupErrors.Add($_.Exception.Message)
    }
  }

  try {
    Remove-OwnedPath $RoamingMarker "Roaming lifecycle marker"
  } catch {
    [void]$CleanupErrors.Add($_.Exception.Message)
  }
  try {
    Remove-OwnedPath $LocalMarker "Local lifecycle marker"
  } catch {
    [void]$CleanupErrors.Add($_.Exception.Message)
  }
  if (-not $RoamingRootExisted) {
    try {
      Remove-OwnedPath $RoamingRoot "Test-created roaming user-data root" -Recurse
    } catch {
      [void]$CleanupErrors.Add($_.Exception.Message)
    }
  }
  if (-not $LocalRootExisted) {
    try {
      Remove-OwnedPath $LocalRoot "Test-created local user-data root" -Recurse
    } catch {
      [void]$CleanupErrors.Add($_.Exception.Message)
    }
  }
  try {
    Remove-OwnedPath $AuditRoot "Lifecycle audit root" -Recurse
  } catch {
    [void]$CleanupErrors.Add($_.Exception.Message)
  }

  try {
    $RemainingRegistration = $UninstallRegistryPaths | Where-Object { Test-Path -LiteralPath $_ }
    if ($RemainingRegistration) {
      throw "Lifecycle cleanup left Winsper uninstall registration behind: $($RemainingRegistration -join ', ')"
    }
  } catch {
    [void]$CleanupErrors.Add($_.Exception.Message)
  }
  foreach ($OwnedArtifact in @($StartupScript, $DesktopShortcut, $ProgramsShortcut)) {
    try {
      if (Test-Path -LiteralPath $OwnedArtifact) {
        throw "Lifecycle cleanup left a Winsper shortcut or launcher behind: $OwnedArtifact"
      }
    } catch {
      [void]$CleanupErrors.Add($_.Exception.Message)
    }
  }
}

if ($LifecycleError) {
  $FailureMessage = $LifecycleError.Exception.Message
  if ($CleanupErrors.Count -gt 0) {
    $FailureMessage += "`nCleanup failures (all cleanup steps were attempted):`n - " + ($CleanupErrors -join "`n - ")
  }
  throw $FailureMessage
}
if ($CleanupErrors.Count -gt 0) {
  throw "Lifecycle validation passed, but cleanup failed after all cleanup steps were attempted:`n - $($CleanupErrors -join "`n - ")"
}

Write-Host "Winsper clean install/uninstall lifecycle ($Mode): PASS"
