"""Bounded Windows-native selected-text readers used by Polish."""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass


_DWORD = ctypes.c_uint32
_LONG = ctypes.c_int32
_ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else _DWORD


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", _LONG),
        ("dy", _LONG),
        ("mouseData", _DWORD),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KeybdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", _DWORD), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeybdInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", _DWORD), ("union", _InputUnion)]


@dataclass(frozen=True)
class UiaSelectionProbe:
    """Result of a non-mutating Windows UI Automation selection probe."""

    supported: bool
    text: str = ""


def probe_uia_selection(window_hwnd: int, *, is_windows: bool) -> UiaSelectionProbe:
    """Read focused selection through UI Automation without modifying app state."""
    if not is_windows or not window_hwnd:
        return UiaSelectionProbe(False)
    initialized = False
    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        initialized = True
        uia_dll = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.CoCreateInstance(
            uia_dll.CUIAutomation().IPersist_GetClassID(),
            interface=uia_dll.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
        element = automation.GetFocusedElement()
        if not element or int(element.CurrentProcessId) != window_process_id(window_hwnd, is_windows=is_windows):
            return UiaSelectionProbe(False)
        raw_pattern = element.GetCurrentPattern(uia_dll.UIA_TextPatternId)
        pattern = raw_pattern.QueryInterface(uia_dll.IUIAutomationTextPattern)
        ranges = pattern.GetSelection()
        selected = [ranges.GetElement(index).GetText(-1) or "" for index in range(ranges.Length)]
        return UiaSelectionProbe(True, "".join(selected))
    except Exception:
        return UiaSelectionProbe(False)
    finally:
        if initialized:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


def wait_for_clipboard_text(pyperclip, *, timeout_seconds: float) -> str:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        value = pyperclip.paste()
        if value:
            return str(value)
        time.sleep(0.025)
    return ""


def send_copy_message(window_hwnd: int, *, is_windows: bool) -> bool:
    """Ask focused native edit control to copy without synthesizing keys."""
    if not is_windows or not window_hwnd:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class GuiThreadInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT),
            ]

        thread_id = int(user32.GetWindowThreadProcessId(window_hwnd, None))
        info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
        if not thread_id or not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) or not info.hwndFocus:
            return False
        result = ctypes.c_size_t()
        return bool(
            user32.SendMessageTimeoutW(
                info.hwndFocus,
                0x0301,  # WM_COPY
                0,
                0,
                0x0002 | 0x0020,  # SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT
                200,
                ctypes.byref(result),
            )
        )
    except Exception:
        return False


def send_copy_shortcut(pyautogui, *, is_windows: bool) -> bool:
    """Send serial Ctrl+C only when no physical modifier can corrupt it."""
    if not is_windows:
        try:
            pyautogui.hotkey("ctrl", "c")
            return True
        except Exception:
            return False
    try:
        user32 = ctypes.windll.user32
        if any(int(user32.GetAsyncKeyState(key)) & 0x8000 for key in (0x11, 0x12, 0x10, 0x5B, 0x5C)):
            return False
        keyeventf_keyup = 0x0002
        inputs = (
            _Input(type=1, ki=_KeybdInput(0x11, 0, 0, 0, 0)),
            _Input(type=1, ki=_KeybdInput(0x43, 0, 0, 0, 0)),
            _Input(type=1, ki=_KeybdInput(0x43, 0, keyeventf_keyup, 0, 0)),
            _Input(type=1, ki=_KeybdInput(0x11, 0, keyeventf_keyup, 0, 0)),
        )
        array = (_Input * len(inputs))(*inputs)
        return int(user32.SendInput(len(array), array, ctypes.sizeof(_Input))) == len(array)
    except Exception:
        return False


def window_process_id(hwnd: int, *, is_windows: bool) -> int:
    if not is_windows or not hwnd:
        return 0
    process_id = ctypes.c_ulong()
    try:
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return int(process_id.value)
    except Exception:
        return 0
