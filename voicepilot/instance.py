from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
WINSPER_INSTANCE_MUTEX = "Local\\Winsper-App"
WINSPER_INSTANCE_LOCK_FILE = "winsper.instance.lock"


def _instance_lock_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "Winsper" / WINSPER_INSTANCE_LOCK_FILE


class SingleInstanceGuard:
    def __init__(self, _config_path: Path) -> None:
        # The mutex identifies the application, not one configuration file.
        # Otherwise --config A and --config B can both own global hotkeys and
        # audio, which is unsafe and indistinguishable to a Windows user.
        self.name = WINSPER_INSTANCE_MUTEX
        self.handle = None
        self.file_handle = None
        self.already_running = False
        self._kernel32 = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._kernel32 = kernel32
        self.handle = handle
        mutex_exists = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

        # A named mutex can be isolated by a packaged/sandboxed host. Hold an
        # exclusive file handle as a second, user-wide boundary so a Codex-run
        # development instance and a terminal/installed instance cannot both
        # own Winsper's global hotkeys and microphone.
        lock_path = _instance_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        ctypes.set_last_error(0)
        file_handle = kernel32.CreateFileW(
            str(lock_path),
            0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
            0,  # no sharing while Winsper owns the file
            None,
            4,  # OPEN_ALWAYS
            0x80,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if file_handle == invalid_handle:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            self.handle = None
            if error in (ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
                self.already_running = True
                return False
            raise ctypes.WinError(error)
        self.file_handle = file_handle
        if mutex_exists:
            self.release()
            self.already_running = True
            return False
        self.already_running = False
        return True

    def release(self) -> None:
        if os.name == "nt" and self._kernel32:
            if self.file_handle:
                self._kernel32.CloseHandle(self.file_handle)
                self.file_handle = None
            if self.handle:
                self._kernel32.CloseHandle(self.handle)
                self.handle = None

    def __enter__(self) -> "SingleInstanceGuard":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()
