from __future__ import annotations

import ctypes
import time


def configure_security_api(kernel32, advapi32) -> None:
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    advapi32.GetTokenInformation.restype = ctypes.c_int


def open_clipboard(user32) -> None:
    deadline = time.monotonic() + 0.5
    while True:
        if user32.OpenClipboard(None):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.02, remaining))
    raise OSError("Windows clipboard is busy. Try again.")


def configure_clipboard_api(user32, kernel32) -> None:
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]


def clipboard_format_is_safe(user32, format_id: int) -> bool:
    # Standard formats backed by movable global memory and safe to clone.
    if format_id in {1, 7, 8, 13, 15, 16, 17}:
        return True
    if format_id < 0xC000:
        return False
    buffer = ctypes.create_unicode_buffer(256)
    length = int(user32.GetClipboardFormatNameW(format_id, buffer, len(buffer)))
    if length <= 0:
        return False
    name = buffer.value.strip().lower()
    return name in {
        "html format",
        "rich text format",
        "png",
        "image/png",
        "text/html",
        "text/rtf",
        "csv",
        "uniformresourcelocator",
        "uniformresourcelocatorw",
    }
