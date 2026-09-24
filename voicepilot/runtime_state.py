from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any

from .storage import atomic_write_json


@dataclass(frozen=True)
class RuntimeState:
    status: str
    detail: str
    paused: bool
    pid: int
    updated_at: str
    process_created_at: int = 0


def runtime_state_path(config_path: Path) -> Path:
    return config_path.parent / "voicepilot.state.json"


def write_runtime_state(config_path: Path, status: str, detail: str = "", paused: bool = False) -> Path:
    path = runtime_state_path(config_path)
    pid = os.getpid()
    payload = {
        "status": status,
        "detail": detail,
        "paused": bool(paused),
        "pid": pid,
        "process_created_at": process_creation_marker(pid),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    atomic_write_json(path, payload)
    return path


def read_runtime_state(config_path: Path, max_age_seconds: int = 300) -> RuntimeState | None:
    path = runtime_state_path(config_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    state = runtime_state_from_dict(payload)
    if state is None:
        return None
    if max_age_seconds > 0 and runtime_state_age_seconds(state) > max_age_seconds:
        return None
    if state.status != "not_running" and not process_is_alive(state.pid):
        return None
    if state.status != "not_running" and state.process_created_at:
        if process_creation_marker(state.pid) != state.process_created_at:
            return None
    return state


def runtime_state_from_dict(payload: dict[str, Any]) -> RuntimeState | None:
    try:
        return RuntimeState(
            status=str(payload.get("status") or ""),
            detail=str(payload.get("detail") or ""),
            paused=bool(payload.get("paused")),
            pid=int(payload.get("pid") or 0),
            updated_at=str(payload.get("updated_at") or ""),
            process_created_at=int(payload.get("process_created_at") or 0),
        )
    except (TypeError, ValueError):
        return None


def runtime_state_age_seconds(state: RuntimeState) -> float:
    try:
        updated = datetime.fromisoformat(state.updated_at)
    except ValueError:
        return float("inf")
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())


def process_is_alive(pid: int) -> bool:
    """Return whether a recorded runtime-state process still exists."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = _windows_process_api()
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def process_creation_marker(pid: int) -> int:
    """Return a stable Windows process-creation marker, or zero when unavailable."""
    if pid <= 0 or os.name != "nt":
        return 0

    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_process_api()
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return 0
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return 0
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


@cache
def _windows_process_api():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32
