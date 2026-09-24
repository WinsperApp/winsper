from __future__ import annotations

import ctypes
import os
from functools import lru_cache


ERROR_INSUFFICIENT_BUFFER = 122
APPMODEL_ERROR_NO_PACKAGE = 15700


@lru_cache(maxsize=1)
def package_full_name() -> str | None:
    """Return the current MSIX package name, or ``None`` when unpackaged."""
    if os.name != "nt":
        return None
    try:
        get_name = ctypes.windll.kernel32.GetCurrentPackageFullName
    except AttributeError:
        return None

    length = ctypes.c_uint32()
    result = get_name(ctypes.byref(length), None)
    if result == APPMODEL_ERROR_NO_PACKAGE:
        return None
    if result != ERROR_INSUFFICIENT_BUFFER or length.value <= 1:
        raise OSError(result, "Windows could not read the current package identity.")

    buffer = ctypes.create_unicode_buffer(length.value)
    result = get_name(ctypes.byref(length), buffer)
    if result:
        raise OSError(result, "Windows could not read the current package identity.")
    return buffer.value or None


def is_packaged_app() -> bool:
    return package_full_name() is not None


def uses_store_updates() -> bool:
    """MSIX production builds are serviced by the Microsoft Store."""
    return is_packaged_app()
