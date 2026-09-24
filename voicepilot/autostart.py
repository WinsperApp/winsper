from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .brand import STARTUP_SCRIPT_NAME
from .distribution import is_packaged_app
from .process_launch import app_command, app_working_directory
from .storage import atomic_write_text


PACKAGED_STARTUP_TASK_ID = "WinsperStartup"


def set_start_with_windows(config_path: Path, enabled: bool) -> None:
    if is_packaged_app():
        _set_packaged_startup(enabled)
        return
    script = startup_script_path()
    if enabled:
        atomic_write_text(script, startup_script_content(config_path))
        return
    try:
        script.unlink(missing_ok=True)
    except OSError:
        pass


def is_start_with_windows_enabled(_config_path: Path | None = None) -> bool:
    if is_packaged_app():
        try:
            return _packaged_startup_task_state("state") == "enabled"
        except RuntimeError:
            return False
    return startup_script_path().exists()


def startup_script_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_SCRIPT_NAME
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_SCRIPT_NAME


def startup_script_content(config_path: Path) -> str:
    app_root = app_working_directory()
    command = subprocess.list2cmdline(
        app_command(
            ["--config", str(config_path.resolve()), "--skip-setup"],
            windowed=True,
        )
    )
    return "\n".join(
        [
            'Set shell = CreateObject("WScript.Shell")',
            f'shell.CurrentDirectory = "{_vbs_string(str(app_root))}"',
            f'shell.Run "{_vbs_string(command)}", 0, False',
            "",
        ]
    )


def _vbs_string(value: str) -> str:
    return value.replace('"', '""')


def _set_packaged_startup(enabled: bool) -> None:
    state = _packaged_startup_task_state("enable" if enabled else "disable")
    if enabled and state == "disabledbyuser":
        raise PermissionError(
            "Launch at login was disabled in Windows. Re-enable Winsper under Settings > Apps > Startup."
        )
    if enabled and state != "enabled":
        raise RuntimeError("Windows could not enable launch at login for Winsper.")
    if not enabled and state == "enabled":
        raise RuntimeError("Windows could not disable launch at login for Winsper.")


def _packaged_startup_task_state(action: str) -> str:
    if action not in {"state", "enable", "disable"}:
        raise ValueError(f"Unsupported startup task action: {action}")
    script = _packaged_startup_script(action)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    state = completed.stdout.strip().splitlines()[-1].strip().casefold() if completed.stdout.strip() else ""
    if completed.returncode or state not in {
        "enabled",
        "disabled",
        "disabledbyuser",
        "disabledbypolicy",
    }:
        raise RuntimeError("Windows could not read Winsper's launch-at-login setting.")
    return state


def _packaged_startup_script(action: str) -> str:
    task_id = PACKAGED_STARTUP_TASK_ID.replace("'", "''")
    return rf"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$startupType = [Windows.ApplicationModel.StartupTask,Windows.ApplicationModel,ContentType=WindowsRuntime]
$stateType = [Windows.ApplicationModel.StartupTaskState,Windows.ApplicationModel,ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
  Where-Object {{ $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 }} |
  Select-Object -First 1
function Wait-WinRt($operation, $resultType) {{
  $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
  return $task.GetAwaiter().GetResult()
}}
$startupTask = Wait-WinRt ($startupType::GetAsync('{task_id}')) $startupType
if ('{action}' -eq 'enable' -and $startupTask.State.ToString() -eq 'Disabled') {{
  $state = Wait-WinRt ($startupTask.RequestEnableAsync()) $stateType
}} elseif ('{action}' -eq 'disable' -and $startupTask.State.ToString() -eq 'Enabled') {{
  $startupTask.Disable()
  $state = $startupTask.State
}} else {{
  $state = $startupTask.State
}}
$state.ToString()
"""
