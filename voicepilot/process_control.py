from __future__ import annotations

import os
import subprocess
import sys
import time


def request_process_windows_close(process_id: int) -> int:
    """Post WM_CLOSE to every top-level window owned by a Windows process."""
    if not sys.platform.startswith("win") or process_id <= 0:
        return 0

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    closed = 0

    @callback_type
    def visit(hwnd, _lparam):
        nonlocal closed
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == process_id:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            closed += 1
        return True

    user32.EnumWindows(visit, 0)
    return closed


def close_process_gracefully(process: subprocess.Popen, timeout: float = 2.0) -> bool:
    """Close a GUI child normally, with terminate/kill as bounded fallbacks."""
    if process.poll() is not None:
        return True

    deadline = time.monotonic() + max(0.0, timeout)
    while process.poll() is None and time.monotonic() < deadline:
        for process_id in process_tree_ids(process.pid):
            request_process_windows_close(process_id)
        try:
            process.wait(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            continue
    if process.poll() is not None:
        return True

    terminate_process_tree(process.pid)
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)
    return False


def process_tree_ids(root_process_id: int) -> list[int]:
    if not sys.platform.startswith("win"):
        return [root_process_id]

    import ctypes
    from ctypes import wintypes

    class ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry32)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry32)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in {None, ctypes.c_void_p(-1).value}:
        return [root_process_id]
    parent_by_pid: dict[int, int] = {}
    try:
        entry = ProcessEntry32()
        entry.dwSize = ctypes.sizeof(ProcessEntry32)
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                parent_by_pid[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    process_ids = [root_process_id]
    changed = True
    while changed:
        changed = False
        for process_id, parent_id in parent_by_pid.items():
            if parent_id in process_ids and process_id not in process_ids:
                process_ids.append(process_id)
                changed = True
    return process_ids


def terminate_process_tree(root_process_id: int) -> None:
    if not sys.platform.startswith("win"):
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    for process_id in reversed(process_tree_ids(root_process_id)):
        process = kernel32.OpenProcess(0x0001, False, process_id)
        if not process:
            continue
        try:
            kernel32.TerminateProcess(process, 1)
        finally:
            kernel32.CloseHandle(process)


def process_is_running(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        process = kernel32.OpenProcess(synchronize, False, process_id)
        if not process:
            return False
        try:
            return kernel32.WaitForSingleObject(process, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(process)
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def watch_owner_process(window, owner_process_id: int):
    """Close a Qt window if the listener process that launched it disappears."""
    if owner_process_id <= 0:
        return None
    from PySide6.QtCore import QTimer

    timer = QTimer(window)
    timer.setInterval(250)

    def close_if_owner_exited() -> None:
        if not process_is_running(owner_process_id):
            timer.stop()
            window.close()

    timer.timeout.connect(close_if_owner_exited)
    timer.start()
    return timer
