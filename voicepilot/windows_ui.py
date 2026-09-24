from __future__ import annotations

import os
import sys
from functools import lru_cache


DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWCP_ROUND = 2
SPI_GETCLIENTAREAANIMATION = 0x1042
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x00000001
PREFERRED_APP_MODE_FORCE_DARK = 2
PREFERRED_APP_MODE_FORCE_LIGHT = 3


def _parse_env_bool(value: str) -> bool | None:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


@lru_cache(maxsize=1)
def prefers_reduced_motion() -> bool:
    override = _parse_env_bool(os.environ.get("WINSPER_REDUCE_MOTION", ""))
    if override is not None:
        return override
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        succeeded = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION,
            0,
            ctypes.byref(enabled),
            0,
        )
        return bool(succeeded) and not bool(enabled.value)
    except (AttributeError, OSError):
        return False


def motion_enabled() -> bool:
    return not prefers_reduced_motion()


@lru_cache(maxsize=1)
def prefers_high_contrast() -> bool:
    """Return the Windows High Contrast preference without requiring Qt."""
    override = _parse_env_bool(os.environ.get("WINSPER_HIGH_CONTRAST", ""))
    if override is not None:
        return override
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class HIGHCONTRASTW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR),
            ]

        value = HIGHCONTRASTW()
        value.cbSize = ctypes.sizeof(value)
        succeeded = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETHIGHCONTRAST,
            value.cbSize,
            ctypes.byref(value),
            0,
        )
        return bool(succeeded) and bool(value.dwFlags & HCF_HIGHCONTRASTON)
    except (AttributeError, OSError):
        return False


def colorref(hex_color: str) -> int:
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected a six-digit color, got {hex_color!r}")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def _set_dwm_attribute(hwnd: int, attribute: int, value: int) -> bool:
    import ctypes

    data = ctypes.c_int(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd),
        ctypes.c_uint(attribute),
        ctypes.byref(data),
        ctypes.sizeof(data),
    )
    return result == 0


def apply_native_window_style(window, palette) -> bool:
    """Apply Windows 11 polish while preserving native frame behavior."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(window.winId())
        if prefers_high_contrast():
            # Keep the system-owned caption, border, and text colors. Overriding
            # them would defeat the user's Windows accessibility scheme.
            return _set_dwm_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        dark = 1 if palette.mode == "dark" else 0
        dark_applied = _set_dwm_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, dark)
        if not dark_applied:
            _set_dwm_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY, dark)
        results = (
            _set_dwm_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND),
            _set_dwm_attribute(hwnd, DWMWA_BORDER_COLOR, colorref(palette.border)),
            _set_dwm_attribute(hwnd, DWMWA_CAPTION_COLOR, colorref(palette.bg)),
            _set_dwm_attribute(hwnd, DWMWA_TEXT_COLOR, colorref(palette.text)),
        )
        return dark_applied or any(results)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def preferred_app_mode(theme: str) -> int:
    """Translate a resolved Winsper theme to the Win32 menu preference."""
    return PREFERRED_APP_MODE_FORCE_LIGHT if theme == "light" else PREFERRED_APP_MODE_FORCE_DARK


def apply_native_menu_theme(theme: str) -> bool:
    """Make native tray menus follow Winsper's explicit light/dark setting.

    Win32 popup menus are owned by the operating system rather than Qt, so a
    Qt stylesheet cannot affect them. Windows 10 1903+ exposes its app-mode
    preference through uxtheme; applying it before pystray creates the popup
    preserves native menu behavior while aligning its colors with Winsper.
    High Contrast remains entirely system controlled.
    """
    if sys.platform != "win32" or prefers_high_contrast():
        return False
    try:
        import ctypes
        from ctypes import wintypes

        if sys.getwindowsversion().build < 18362:
            return False
        uxtheme = ctypes.WinDLL("uxtheme", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetProcAddress.argtypes = (wintypes.HMODULE, ctypes.c_void_p)
        kernel32.GetProcAddress.restype = ctypes.c_void_p
        set_mode_address = kernel32.GetProcAddress(uxtheme._handle, ctypes.c_void_p(135))
        flush_address = kernel32.GetProcAddress(uxtheme._handle, ctypes.c_void_p(136))
        if not set_mode_address or not flush_address:
            return False
        set_preferred_app_mode = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int)(set_mode_address)
        flush_menu_themes = ctypes.WINFUNCTYPE(None)(flush_address)
        set_preferred_app_mode(preferred_app_mode(theme))
        flush_menu_themes()
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def animate_progress_value(progress_bar, value: int, *, duration_ms: int = 120) -> None:
    value = max(progress_bar.minimum(), min(progress_bar.maximum(), int(value)))
    if not motion_enabled() or progress_bar.maximum() <= progress_bar.minimum():
        progress_bar.setValue(value)
        return

    from PySide6.QtCore import QEasingCurve, QPropertyAnimation

    current = progress_bar.value()
    if current == value:
        return
    previous = getattr(progress_bar, "_winsper_progress_animation", None)
    if previous is not None:
        previous.stop()
    animation = QPropertyAnimation(progress_bar, b"value", progress_bar)
    animation.setDuration(duration_ms)
    animation.setStartValue(current)
    animation.setEndValue(value)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    progress_bar._winsper_progress_animation = animation
    animation.start()
